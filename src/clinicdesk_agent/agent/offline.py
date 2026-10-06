"""Deterministic, rule-based stand-in for an LLM (offline demo mode and evaluation baseline).

It speaks the same tool-calling protocol as a real model: it reads the
conversation, emits :class:`ToolCall` objects, and turns tool results into a
reply. That means the offline demo exercises exactly the same orchestrator,
validation and scheduling code paths as a hosted model would.
"""

from __future__ import annotations

import json
import re
from typing import Any, Sequence

from clinicdesk_agent.agent.llm import AssistantTurn, ToolCall
from clinicdesk_agent.dates import find_date_phrase, find_part_of_day
from clinicdesk_agent.safety.triage import match_specialty_name, suggest_specialty

HELP_TEXT = ("I can help you choose a specialty, find free slots and book, cancel or move appointments. "
             "Try: 'find a dermatology slot tomorrow morning', 'book slot 12', 'my appointments' or "
             "describe your symptoms.")

_GREETING = re.compile(r"^\s*(?:hi|hello|hey|good (?:morning|afternoon|evening))\b[\s!.,]*$", re.IGNORECASE)
_ORDINALS = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "fifth": 4}
_SEARCH_WORDS = re.compile(r"\b(?:slots?|availab\w*|appointments?|openings?|free|schedule|see (?:a|an|dr)|"
                           r"book|when can|earliest)\b", re.IGNORECASE)
_SYMPTOM_WORDS = re.compile(r"\b(?:pain|hurts?|aches?|aching|feel(?:ing)?|symptoms?|sick|sore|itchy|swollen)\b",
                            re.IGNORECASE)
_DOCTOR_NAME = re.compile(r"\b(?:dr\.?|doctor)\s+([a-z][a-z'-]+(?:\s+[a-z][a-z'-]+)?)", re.IGNORECASE)
_NOT_A_NAME = {"for", "on", "at", "in", "tomorrow", "today", "next", "this", "about", "appointment", "slot"}


def _last_user_text(messages: Sequence[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message["role"] == "user":
            return message["content"]
    return ""


def _trailing_tool_results(messages: Sequence[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    results = []
    for message in reversed(messages):
        if message["role"] != "tool":
            break
        results.append((message.get("name", ""), json.loads(message["content"])))
    return list(reversed(results))


def _results_since_last_user(messages: Sequence[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    results = []
    for message in reversed(messages):
        if message["role"] == "user":
            break
        if message["role"] == "tool":
            results.append((message.get("name", ""), json.loads(message["content"])))
    return list(reversed(results))


def _last_search_slot_ids(messages: Sequence[dict[str, Any]]) -> list[int]:
    for message in reversed(messages):
        if message["role"] == "tool" and message.get("name") == "search_slots":
            payload = json.loads(message["content"])
            return [s["slot_id"] for s in payload.get("slots", [])]
    return []


def _doctor_name(text: str) -> str | None:
    match = _DOCTOR_NAME.search(text)
    if not match:
        return None
    words = [w for w in match.group(1).split() if w.lower() not in _NOT_A_NAME]
    return " ".join(words) or None


def _search_args(text: str, specialty: str | None = None) -> dict[str, Any]:
    args: dict[str, Any] = {}
    specialty = specialty or match_specialty_name(text)
    if specialty:
        args["specialty"] = specialty
    doctor = _doctor_name(text)
    if doctor:
        args["doctor_name"] = doctor
    date_phrase = find_date_phrase(text)
    if date_phrase:
        args["date"] = date_phrase
    part = find_part_of_day(text)
    if part:
        args["part_of_day"] = part
    return args


class RuleBasedChatModel:
    """A small intent parser that drives the real tools without any network access."""

    def complete(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> AssistantTurn:
        results = _trailing_tool_results(messages)
        if results:
            follow_up = self._follow_up(messages, results)
            return follow_up or AssistantTurn(text=self._compose(_results_since_last_user(messages)))
        return self._plan(messages, _last_user_text(messages))

    # ------------------------------------------------------------------ planning
    @staticmethod
    def _call(messages: Sequence[dict[str, Any]], name: str, **arguments: Any) -> AssistantTurn:
        call = ToolCall(id=f"call_{len(messages)}", name=name, arguments=arguments,
                        raw_arguments=json.dumps(arguments))
        return AssistantTurn(tool_calls=(call,))

    def _plan(self, messages: Sequence[dict[str, Any]], text: str) -> AssistantTurn:
        lowered = text.lower()
        if _GREETING.match(text):
            return AssistantTurn(text="Hello! " + HELP_TEXT)
        if re.search(r"\b(?:help|what can you do)\b", lowered):
            return AssistantTurn(text=HELP_TEXT)
        if re.search(r"\bmy (?:appointments?|bookings?)\b|\bwhat (?:have i|did i) book", lowered):
            return self._call(messages, "list_my_appointments")

        move = re.search(r"\b(?:move|reschedule|change)\b\D*?(\d+)\D+?(?:slot\s*#?|to\s*#?)(\d+)", lowered)
        if move:
            return self._call(messages, "request_reschedule", booking_id=int(move.group(1)),
                              new_slot_id=int(move.group(2)))
        cancel = re.search(r"\bcancel\b\D*?(\d+)", lowered)
        if cancel:
            return self._call(messages, "request_cancellation", booking_id=int(cancel.group(1)))
        if re.search(r"\bcancel\b", lowered):
            return self._call(messages, "list_my_appointments")

        if re.search(r"\bbook\b", lowered):
            explicit = re.search(r"(?:slot\s*#?|#|book\s+)(\d+)\b", lowered)
            if explicit:
                return self._call(messages, "request_booking", slot_id=int(explicit.group(1)))
            ordinal = re.search(r"\b(" + "|".join(_ORDINALS) + r")\b", lowered)
            if ordinal:
                ids = _last_search_slot_ids(messages)
                index = _ORDINALS[ordinal.group(1)]
                if index < len(ids):
                    return self._call(messages, "request_booking", slot_id=ids[index])
                return AssistantTurn(text="I don't have that option on screen. Search for slots first.")

        if re.search(r"\b(?:specialt(?:y|ies)|departments?)\b", lowered) and re.search(
                r"\b(?:what|which|list)\b", lowered):
            return self._call(messages, "list_specialties")
        if re.search(r"\b(?:which|list|who are the)\b.*\bdoctors\b", lowered):
            args = {"specialty": s} if (s := match_specialty_name(text)) else {}
            return self._call(messages, "find_doctors", **args)

        has_symptoms = bool(_SYMPTOM_WORDS.search(text)) or suggest_specialty(text).confident
        explicit_target = match_specialty_name(text) or _doctor_name(text)
        if has_symptoms and not explicit_target:
            return self._call(messages, "triage_symptoms", symptoms=text)
        if _SEARCH_WORDS.search(text) or explicit_target or find_date_phrase(text):
            return self._call(messages, "search_slots", **_search_args(text))
        return AssistantTurn(text="Sorry, I didn't catch that. " + HELP_TEXT)

    def _follow_up(self, messages: Sequence[dict[str, Any]],
                   results: list[tuple[str, dict[str, Any]]]) -> AssistantTurn | None:
        """Chain triage -> search when the patient also asked for a slot in the same message."""
        name, payload = results[-1]
        if name != "triage_symptoms" or not payload.get("ok") or payload.get("emergency"):
            return None
        text = _last_user_text(messages)
        if not (_SEARCH_WORDS.search(text) or find_date_phrase(text)):
            return None
        return self._call(messages, "search_slots", **_search_args(text, payload["suggested_specialty"]))

    # ------------------------------------------------------------------ wording
    def _compose(self, results: list[tuple[str, dict[str, Any]]]) -> str:
        return "\n\n".join(self._describe(name, payload) for name, payload in results)

    @staticmethod
    def _describe(name: str, payload: dict[str, Any]) -> str:
        if not payload.get("ok"):
            extra = ""
            if payload.get("specialties"):
                extra = " Available specialties: " + ", ".join(payload["specialties"]) + "."
            return f"Sorry, {payload.get('message', 'that did not work')}.{extra}"
        if name == "triage_symptoms":
            if not payload["confident"]:
                return (f"I couldn't match your symptoms to a specific specialty, so {payload['suggested_specialty']} "
                        "is a sensible first stop. Would you like me to look for a slot?")
            matched = ", ".join(payload["matched_keywords"])
            return (f"Based on what you mention ({matched}), {payload['suggested_specialty']} looks like the right "
                    f"place to start. Say e.g. 'find a {payload['suggested_specialty']} slot tomorrow' to see times.")
        if name == "search_slots":
            if not payload["slots"]:
                return "No free slots match that. Try another day, part of the day or specialty."
            lines = [f"- Slot {s['slot_id']}: {s['doctor']} ({s['specialty']}), {s['when']}" for s in payload["slots"]]
            return "Here are the earliest free slots:\n" + "\n".join(lines) + "\nSay 'book slot N' to book one."
        if name in ("request_booking", "request_cancellation", "request_reschedule"):
            return "I've prepared that change; nothing is final until you confirm."
        if name == "list_my_appointments":
            if not payload["appointments"]:
                return "You have no upcoming appointments."
            lines = [f"- Booking {a['booking_id']}: {a['doctor']} ({a['specialty']}), {a['when']}"
                     for a in payload["appointments"]]
            return "Your upcoming appointments:\n" + "\n".join(lines)
        if name == "list_specialties":
            return "We offer: " + ", ".join(payload["specialties"]) + "."
        if name == "find_doctors":
            if not payload["doctors"]:
                return "No doctors match that."
            return "Doctors: " + "; ".join(f"{d['name']} ({d['specialty']})" for d in payload["doctors"]) + "."
        return json.dumps(payload)
