"""Scripted-dialogue evaluation: routing, reply type, booking outcomes and DB invariants.

Each dialogue runs against a fresh, seeded database and a fixed clock, so the
same model always gets the same score. Works with any :class:`ChatModel`
(the offline rule-based model by default, or a hosted model).
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, time
from importlib import resources
from pathlib import Path
from typing import Any, Callable

from clinicdesk_agent.agent.llm import ChatModel
from clinicdesk_agent.agent.offline import RuleBasedChatModel
from clinicdesk_agent.agent.tools import Session
from clinicdesk_agent.app import build_clinic_desk
from clinicdesk_agent.config import Settings
from clinicdesk_agent.db.seed import seed_database
from clinicdesk_agent.scheduling import check_invariants

EVAL_TODAY = date(2026, 1, 5)  # a Monday, so "tomorrow" is a clinic day
EVAL_PASSCODE = "eval-passcode-123"  # synthetic, only ever used inside a temporary database


def load_dialogues(path: Path | None = None) -> list[dict[str, Any]]:
    if path is not None:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    text = resources.files("clinicdesk_agent.evaluation").joinpath("dialogues.json").read_text(encoding="utf-8")
    return json.loads(text)


@dataclass
class TurnOutcome:
    dialogue: str
    user: str
    tools_called: list[str]
    kind: str
    failures: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    dialogues: int = 0
    dialogues_passed: int = 0
    routed_turns: int = 0
    routing_correct: int = 0
    kind_turns: int = 0
    kind_correct: int = 0
    booking_checks: int = 0
    booking_correct: int = 0
    invariant_violations: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    turns: list[TurnOutcome] = field(default_factory=list)

    @staticmethod
    def _rate(num: int, den: int) -> float:
        return round(num / den, 3) if den else 1.0

    def summary(self) -> dict[str, Any]:
        return {
            "dialogues_passed": f"{self.dialogues_passed}/{self.dialogues}",
            "routing_accuracy": self._rate(self.routing_correct, self.routed_turns),
            "reply_type_accuracy": self._rate(self.kind_correct, self.kind_turns),
            "booking_outcome_accuracy": self._rate(self.booking_correct, self.booking_checks),
            "invariant_violations": len(self.invariant_violations),
            "failures": self.failures,
        }


class _State:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}

    def fill(self, text: str) -> str:
        for key, value in self.values.items():
            text = text.replace("{" + key + "}", str(value))
        return text


def _first_listed_slot(session: Session) -> int | None:
    for message in reversed(session.history):
        if message["role"] == "tool" and message.get("name") == "search_slots":
            slots = json.loads(message["content"]).get("slots", [])
            return slots[0]["slot_id"] if slots else None
    return None


def run_dialogue(dialogue: dict[str, Any], model_factory: Callable[[], ChatModel], workdir: Path,
                 report: EvalReport, *, seed: int = 7) -> bool:
    settings = Settings(db_path=workdir / f"{dialogue['id']}.db", timezone="UTC")
    clock = lambda: datetime.combine(EVAL_TODAY, time(8, 0))  # noqa: E731
    desk = build_clinic_desk(settings, model=model_factory(), clock=clock)
    seed_database(desk.db, seed=seed, today=EVAL_TODAY, days=10)

    sessions: dict[str, Session] = {}
    expected_bookings: dict[str, int] = dialogue.get("expect_active_bookings", {})
    for handle in {"eval-a", *expected_bookings, *(t.get("as", "eval-a") for t in dialogue["turns"])}:
        patient = desk.patients.register(handle, EVAL_PASSCODE, now=clock())
        sessions[handle] = Session(patient.patient_id, patient.handle)

    state, ok = _State(), True
    for turn in dialogue["turns"]:
        session = sessions[turn.get("as", "eval-a")]
        user_text = state.fill(turn["user"])
        reply = desk.orchestrator.handle(session, user_text)
        outcome = TurnOutcome(dialogue["id"], user_text, reply.tools_called, reply.kind)
        if "expect_tools" in turn:
            report.routed_turns += 1
            if reply.tools_called == turn["expect_tools"]:
                report.routing_correct += 1
            else:
                outcome.failures.append(f"tools {reply.tools_called} != {turn['expect_tools']}")
        if "expect_kind" in turn:
            report.kind_turns += 1
            if reply.kind == turn["expect_kind"]:
                report.kind_correct += 1
            else:
                outcome.failures.append(f"kind {reply.kind!r} != {turn['expect_kind']!r}")
        for needle in turn.get("expect_text", []):
            if needle.lower() not in reply.text.lower():
                outcome.failures.append(f"reply lacks {needle!r}")
        if reply.result and reply.result.get("ok") and "appointment" in reply.result:
            state.values["last_booking_id"] = reply.result["appointment"]["booking_id"]
            state.values["last_booked_slot"] = reply.result["appointment"]["slot_id"]
        listed = _first_listed_slot(session)
        if listed is not None:
            state.values["first_listed_slot"] = listed
        if outcome.failures:
            ok = False
            report.failures.extend(f"{dialogue['id']}: '{user_text}': {f}" for f in outcome.failures)
        report.turns.append(outcome)

    for handle, expected in expected_bookings.items():
        report.booking_checks += 1
        actual = len(desk.bookings.list_for_patient(sessions[handle].patient_id))
        if actual == expected:
            report.booking_correct += 1
        else:
            ok = False
            report.failures.append(f"{dialogue['id']}: {handle} has {actual} bookings, expected {expected}")
    violations = check_invariants(desk.db)
    if violations:
        ok = False
        report.invariant_violations.extend(f"{dialogue['id']}: {v}" for v in violations)
    return ok


def run_evaluation(model_factory: Callable[[], ChatModel] = RuleBasedChatModel,
                   dialogues: list[dict[str, Any]] | None = None, *, seed: int = 7) -> EvalReport:
    report = EvalReport()
    dialogues = dialogues if dialogues is not None else load_dialogues()
    with tempfile.TemporaryDirectory(prefix="clinicdesk-eval-") as tmp:
        for dialogue in dialogues:
            report.dialogues += 1
            if run_dialogue(dialogue, model_factory, Path(tmp), report, seed=seed):
                report.dialogues_passed += 1
    return report
