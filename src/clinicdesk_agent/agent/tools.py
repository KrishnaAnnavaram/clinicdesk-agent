"""Typed tools the language model may call, and the session state they act on.

Security properties enforced here, in code:

* The model can only call the tools listed in :data:`TOOL_SPECS`; arguments are
  validated against the declared schema and unknown keys are rejected. In
  particular there is no ``patient_id`` argument anywhere: the patient is
  always taken from the authenticated :class:`Session`.
* Read tools use a read-only database connection and never return other
  patients' data.
* "Write" tools only *propose* an action (``request_*``). The change is applied
  by :meth:`Toolbox.apply_pending` after the patient explicitly confirms, and
  the orchestrator, not the model, decides when that happens.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from clinicdesk_agent.agent.llm import ToolCall
from clinicdesk_agent.dates import PARTS_OF_DAY, DateParseError, resolve_date_phrase
from clinicdesk_agent.db import Database
from clinicdesk_agent.safety import TRIAGE_DISCLAIMER, emergency_message, screen_for_emergency, suggest_specialty
from clinicdesk_agent.scheduling import errors
from clinicdesk_agent.scheduling.booking import BookingService, Clock
from clinicdesk_agent.scheduling.models import describe_time
from clinicdesk_agent.scheduling.slots import find_doctors, get_slot, list_specialties, search_open_slots

MAX_STRING_ARG = 300


# --------------------------------------------------------------------------- schema
@dataclass(frozen=True)
class Param:
    name: str
    type: str  # "string" | "integer"
    description: str
    required: bool = False
    enum: tuple[str, ...] | None = None
    minimum: int | None = None
    maximum: int | None = None

    def schema(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.type, "description": self.description}
        if self.enum:
            out["enum"] = list(self.enum)
        if self.minimum is not None:
            out["minimum"] = self.minimum
        if self.maximum is not None:
            out["maximum"] = self.maximum
        return out


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    params: tuple[Param, ...] = ()

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {p.name: p.schema() for p in self.params},
                "required": [p.name for p in self.params if p.required],
                "additionalProperties": False,
            },
        }


class ToolArgumentError(ValueError):
    pass


def validate_arguments(spec: ToolSpec, args: dict[str, Any] | None) -> dict[str, Any]:
    if args is None:
        raise ToolArgumentError("arguments were not valid JSON")
    if not isinstance(args, dict):
        raise ToolArgumentError("arguments must be a JSON object")
    known = {p.name: p for p in spec.params}
    unknown = sorted(set(args) - set(known))
    if unknown:
        raise ToolArgumentError(f"unknown argument(s) {unknown}; allowed: {sorted(known)}")
    clean: dict[str, Any] = {}
    for param in spec.params:
        value = args.get(param.name)
        if value is None or (isinstance(value, str) and not value.strip()):
            if param.required:
                raise ToolArgumentError(f"missing required argument {param.name!r}")
            continue
        if param.type == "integer":
            if isinstance(value, bool):
                raise ToolArgumentError(f"{param.name} must be an integer")
            try:
                value = int(str(value).strip().lstrip("#"))
            except ValueError as exc:
                raise ToolArgumentError(f"{param.name} must be an integer") from exc
            if param.minimum is not None and value < param.minimum:
                raise ToolArgumentError(f"{param.name} must be >= {param.minimum}")
            if param.maximum is not None and value > param.maximum:
                raise ToolArgumentError(f"{param.name} must be <= {param.maximum}")
        else:
            if not isinstance(value, str):
                raise ToolArgumentError(f"{param.name} must be a string")
            value = value.strip()
            if len(value) > MAX_STRING_ARG:
                raise ToolArgumentError(f"{param.name} is too long")
            if param.enum:
                lowered = {e.lower(): e for e in param.enum}
                if value.lower() not in lowered:
                    raise ToolArgumentError(f"{param.name} must be one of {list(param.enum)}")
                value = lowered[value.lower()]
        clean[param.name] = value
    return clean


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec("triage_symptoms",
             "Suggest which specialty to book for the symptoms the patient described. Not a diagnosis.",
             (Param("symptoms", "string", "The patient's own description of their symptoms.", required=True),)),
    ToolSpec("list_specialties", "List the specialties this clinic offers."),
    ToolSpec("find_doctors", "List doctors, optionally filtered by specialty or (part of) a name.",
             (Param("specialty", "string", "Specialty name, e.g. 'Cardiology'."),
              Param("doctor_name", "string", "Full or partial doctor name."))),
    ToolSpec("search_slots",
             "Find free appointment slots. Returns slot ids; book only ids returned by this tool.",
             (Param("specialty", "string", "Specialty name, e.g. 'Dermatology'."),
              Param("doctor_name", "string", "Full or partial doctor name."),
              Param("date", "string", "Day or range in the patient's words: 'tomorrow', 'Friday', "
                                      "'next week', 'Oct 14' or 'YYYY-MM-DD'."),
              Param("part_of_day", "string", "Preferred part of the day.", enum=tuple(PARTS_OF_DAY)),
              Param("limit", "integer", "Maximum slots to return.", minimum=1, maximum=20))),
    ToolSpec("request_booking",
             "Propose booking one slot for the signed-in patient. The patient must confirm before it is booked.",
             (Param("slot_id", "integer", "A slot_id returned by search_slots.", required=True, minimum=1),)),
    ToolSpec("list_my_appointments", "List the signed-in patient's upcoming appointments."),
    ToolSpec("request_cancellation",
             "Propose cancelling one of the signed-in patient's appointments. Needs confirmation.",
             (Param("booking_id", "integer", "A booking_id from list_my_appointments.", required=True, minimum=1),)),
    ToolSpec("request_reschedule",
             "Propose moving one of the patient's appointments to another free slot. Needs confirmation.",
             (Param("booking_id", "integer", "A booking_id from list_my_appointments.", required=True, minimum=1),
              Param("new_slot_id", "integer", "A slot_id returned by search_slots.", required=True, minimum=1))),
)
SPEC_BY_NAME = {s.name: s for s in TOOL_SPECS}


# --------------------------------------------------------------------------- session
@dataclass
class PendingAction:
    kind: str  # "book" | "cancel" | "reschedule"
    summary: str
    slot_id: int | None = None
    booking_id: int | None = None
    idempotency_key: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class Session:
    """Per-conversation state. ``patient_id`` comes from authentication, never from the model."""

    patient_id: int
    handle: str
    history: list[dict[str, Any]] = field(default_factory=list)
    pending: PendingAction | None = None


def _fail(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error": code, "message": message, **extra}


# --------------------------------------------------------------------------- toolbox
class Toolbox:
    def __init__(self, db: Database, bookings: BookingService, clock: Clock, *, emergency_number: str = "911") -> None:
        self.db = db
        self.bookings = bookings
        self.clock = clock
        self.emergency_number = emergency_number
        self._handlers: dict[str, Callable[[Session, dict[str, Any]], dict[str, Any]]] = {
            "triage_symptoms": self._triage,
            "list_specialties": self._list_specialties,
            "find_doctors": self._find_doctors,
            "search_slots": self._search_slots,
            "request_booking": self._request_booking,
            "list_my_appointments": self._list_my_appointments,
            "request_cancellation": self._request_cancellation,
            "request_reschedule": self._request_reschedule,
        }

    @staticmethod
    def schemas() -> list[dict[str, Any]]:
        return [s.schema() for s in TOOL_SPECS]

    def execute(self, session: Session, call: ToolCall) -> dict[str, Any]:
        spec = SPEC_BY_NAME.get(call.name)
        if spec is None:
            return _fail("unknown_tool", f"no tool named {call.name!r}", available=sorted(SPEC_BY_NAME))
        try:
            args = validate_arguments(spec, call.arguments)
        except ToolArgumentError as exc:
            return _fail("invalid_arguments", str(exc))
        try:
            return self._handlers[call.name](session, args)
        except errors.SchedulingError as exc:
            return _fail(exc.code, str(exc))

    # ---- read tools
    def _triage(self, session: Session, args: dict[str, Any]) -> dict[str, Any]:
        flag = screen_for_emergency(args["symptoms"])
        if flag:
            return {"ok": True, "emergency": True, "message": emergency_message(flag.reason, self.emergency_number)}
        suggestion = suggest_specialty(args["symptoms"])
        return {
            "ok": True,
            "emergency": False,
            "suggested_specialty": suggestion.specialty,
            "confident": suggestion.confident,
            "matched_keywords": list(suggestion.matched_keywords),
            "alternatives": list(suggestion.alternatives),
            "disclaimer": TRIAGE_DISCLAIMER,
        }

    def _list_specialties(self, session: Session, args: dict[str, Any]) -> dict[str, Any]:
        with self.db.reader() as conn:
            return {"ok": True, "specialties": list_specialties(conn)}

    def _known_specialty(self, conn, name: str) -> str | None:
        return next((s for s in list_specialties(conn) if s.lower() == name.lower()), None)

    def _find_doctors(self, session: Session, args: dict[str, Any]) -> dict[str, Any]:
        with self.db.reader() as conn:
            doctors = find_doctors(conn, specialty=args.get("specialty"), name_query=args.get("doctor_name"))
        return {"ok": True, "doctors": [{"name": d.name, "specialty": d.specialty} for d in doctors]}

    def _search_slots(self, session: Session, args: dict[str, Any]) -> dict[str, Any]:
        now = self.clock()
        date_range = None
        if "date" in args:
            try:
                date_range = resolve_date_phrase(args["date"], now.date())
            except DateParseError as exc:
                return _fail("invalid_date", str(exc))
        with self.db.reader() as conn:
            specialty = None
            if "specialty" in args:
                specialty = self._known_specialty(conn, args["specialty"])
                if specialty is None:
                    return _fail("unknown_specialty", f"no specialty {args['specialty']!r}",
                                 specialties=list_specialties(conn))
            doctor_ids = None
            if "doctor_name" in args:
                doctors = find_doctors(conn, specialty=specialty, name_query=args["doctor_name"])
                if not doctors:
                    return _fail("doctor_not_found", f"no doctor matching {args['doctor_name']!r}")
                doctor_ids = [d.doctor_id for d in doctors]
            window = PARTS_OF_DAY[args["part_of_day"]] if "part_of_day" in args else None
            slots = search_open_slots(conn, now=now, specialty=specialty, doctor_ids=doctor_ids,
                                      date_range=date_range, window=window, limit=args.get("limit", 8))
        result: dict[str, Any] = {"ok": True, "count": len(slots), "slots": [s.to_public_dict() for s in slots]}
        if date_range is not None:
            result["resolved_dates"] = {"from": date_range.start.isoformat(), "to": date_range.end.isoformat()}
        return result

    def _list_my_appointments(self, session: Session, args: dict[str, Any]) -> dict[str, Any]:
        bookings = self.bookings.list_for_patient(session.patient_id)
        return {"ok": True, "appointments": [b.to_owner_dict() for b in bookings]}

    # ---- proposal tools (no writes)
    def _open_future_slot(self, slot_id: int):
        with self.db.reader() as conn:
            slot = get_slot(conn, slot_id)
        if slot is None:
            raise errors.SlotNotFound(f"slot {slot_id} does not exist; use search_slots to find one")
        if slot.start_at <= self.clock():
            raise errors.SlotInPast(f"slot {slot_id} is in the past")
        if slot.is_booked:
            raise errors.SlotUnavailable(f"slot {slot_id} is already taken; search again")
        return slot

    def _owned_booking(self, session: Session, booking_id: int):
        for booking in self.bookings.list_for_patient(session.patient_id):
            if booking.booking_id == booking_id:
                return booking
        raise errors.BookingNotFound(f"you have no upcoming appointment with id {booking_id}")

    def _request_booking(self, session: Session, args: dict[str, Any]) -> dict[str, Any]:
        slot = self._open_future_slot(args["slot_id"])
        summary = f"Book {slot.doctor_name} ({slot.specialty}) on {describe_time(slot.start_at)} [slot {slot.slot_id}]"
        session.pending = PendingAction("book", summary, slot_id=slot.slot_id)
        return {"ok": True, "status": "awaiting_confirmation", "summary": summary}

    def _request_cancellation(self, session: Session, args: dict[str, Any]) -> dict[str, Any]:
        booking = self._owned_booking(session, args["booking_id"])
        summary = (f"Cancel your appointment with {booking.doctor_name} on {describe_time(booking.start_at)} "
                   f"[booking {booking.booking_id}]")
        session.pending = PendingAction("cancel", summary, booking_id=booking.booking_id)
        return {"ok": True, "status": "awaiting_confirmation", "summary": summary}

    def _request_reschedule(self, session: Session, args: dict[str, Any]) -> dict[str, Any]:
        booking = self._owned_booking(session, args["booking_id"])
        slot = self._open_future_slot(args["new_slot_id"])
        summary = (f"Move your appointment with {booking.doctor_name} on {describe_time(booking.start_at)} to "
                   f"{slot.doctor_name} on {describe_time(slot.start_at)} [booking {booking.booking_id} -> "
                   f"slot {slot.slot_id}]")
        session.pending = PendingAction("reschedule", summary, slot_id=slot.slot_id, booking_id=booking.booking_id)
        return {"ok": True, "status": "awaiting_confirmation", "summary": summary}

    # ---- applied only after explicit confirmation
    def apply_pending(self, session: Session) -> dict[str, Any]:
        pending, session.pending = session.pending, None
        if pending is None:
            return _fail("nothing_pending", "there is nothing waiting for confirmation")
        try:
            if pending.kind == "book":
                booking = self.bookings.book(session.patient_id, pending.slot_id,
                                             idempotency_key=pending.idempotency_key)
                return {"ok": True, "action": "booked", "appointment": booking.to_owner_dict()}
            if pending.kind == "cancel":
                booking = self.bookings.cancel(session.patient_id, pending.booking_id)
                return {"ok": True, "action": "cancelled", "appointment": booking.to_owner_dict()}
            if pending.kind == "reschedule":
                booking = self.bookings.reschedule(session.patient_id, pending.booking_id, pending.slot_id)
                return {"ok": True, "action": "rescheduled", "appointment": booking.to_owner_dict()}
        except errors.SchedulingError as exc:
            return _fail(exc.code, str(exc))
        return _fail("unknown_action", f"unsupported pending action {pending.kind!r}")  # pragma: no cover


def to_tool_message(call: ToolCall, result: dict[str, Any]) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call.id, "name": call.name, "content": json.dumps(result, default=str)}
