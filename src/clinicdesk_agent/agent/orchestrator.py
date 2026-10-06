"""Conversation loop around a tool-calling model.

Order of operations for every user message (all enforced in code):

1. Emergency red-flag screen. On a match the model is never called.
2. Pending confirmation. "yes" applies the proposed booking/cancellation via
   the scheduling service; "no" drops it; anything else abandons it.
3. Diagnosis / prescription requests get a fixed refusal.
4. Bounded tool-calling loop (``max_steps``). Model or tool failures become a
   friendly message instead of an exception in the UI.
5. If triage ran, the "not medical advice" disclaimer is appended; if a
   proposal is pending, a canonical confirmation question is appended.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from clinicdesk_agent.agent.llm import ChatModel, LLMError
from clinicdesk_agent.agent.prompts import build_system_prompt
from clinicdesk_agent.agent.tools import Session, Toolbox, to_tool_message
from clinicdesk_agent.safety import (
    ADVICE_REFUSAL,
    TRIAGE_DISCLAIMER,
    emergency_message,
    is_medical_advice_request,
    screen_for_emergency,
)
from clinicdesk_agent.scheduling.models import describe_time, from_db_time

MAX_INPUT_CHARS = 2000
_AFFIRM = re.compile(r"^\s*(?:yes|y|yeah|yep|sure|confirm(?:ed)?|ok(?:ay)?|please do|go ahead|do it|book it)\b",
                     re.IGNORECASE)
_DENY = re.compile(r"^\s*(?:no|n|nope|don'?t|do not|stop|never ?mind|not now)\b", re.IGNORECASE)

UNAVAILABLE = ("Sorry, the assistant is unavailable right now. Nothing was booked or changed. "
               "Please try again in a moment.")
TOO_MANY_STEPS = ("Sorry, I couldn't finish that request. Nothing was booked or changed. "
                  "Could you ask for one thing at a time?")


@dataclass
class Reply:
    text: str
    kind: str = "answer"  # answer | emergency | refusal | confirm | done | error
    tools_called: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None


def is_affirmative(text: str) -> bool:
    return bool(_AFFIRM.match(text)) and not _DENY.match(text)


def is_negative(text: str) -> bool:
    return bool(_DENY.match(text))


def describe_outcome(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return f"I couldn't complete that: {result.get('message', 'unknown error')}. Nothing was changed."
    appt = result["appointment"]
    when = describe_time(from_db_time(appt["start"]))
    verb = {"booked": "Booked", "cancelled": "Cancelled", "rescheduled": "Moved"}.get(result["action"], "Done")
    if result["action"] == "cancelled":
        return f"{verb}: your appointment with {appt['doctor']} on {when}."
    return f"{verb}: {appt['doctor']} ({appt['specialty']}) on {when}. Booking number {appt['booking_id']}."


class Orchestrator:
    def __init__(self, model: ChatModel, toolbox: Toolbox, *, timezone: str = "UTC", max_steps: int = 4,
                 emergency_number: str = "911", history_limit: int = 24) -> None:
        self.model = model
        self.toolbox = toolbox
        self.timezone = timezone
        self.max_steps = max_steps
        self.emergency_number = emergency_number
        self.history_limit = history_limit

    # ------------------------------------------------------------------ helpers
    def _remember(self, session: Session, user_text: str | None, reply: Reply) -> Reply:
        if user_text is not None:
            session.history.append({"role": "user", "content": user_text})
        session.history.append({"role": "assistant", "content": reply.text})
        self._trim(session)
        return reply

    def _trim(self, session: Session) -> None:
        history = session.history
        if len(history) <= self.history_limit:
            return
        # Cut only at a user message so assistant tool calls stay paired with their results.
        start = len(history) - self.history_limit
        while start < len(history) and history[start]["role"] != "user":
            start += 1
        session.history = history[start:]

    # ------------------------------------------------------------------ confirmations
    def confirm(self, session: Session) -> Reply:
        result = self.toolbox.apply_pending(session)
        kind = "done" if result.get("ok") else "error"
        return self._remember(session, None, Reply(describe_outcome(result), kind, result=result))

    def decline(self, session: Session) -> Reply:
        session.pending = None
        return self._remember(session, None, Reply("OK, I haven't changed anything. What would you like to do?"))

    # ------------------------------------------------------------------ main entry
    def handle(self, session: Session, text: str) -> Reply:
        text = (text or "").strip()[:MAX_INPUT_CHARS]
        if not text:
            return Reply("Please type a message.")

        flag = screen_for_emergency(text)
        if flag:
            session.pending = None
            return self._remember(session, text, Reply(emergency_message(flag.reason, self.emergency_number),
                                                       "emergency"))

        if session.pending is not None:
            if is_affirmative(text):
                session.history.append({"role": "user", "content": text})
                return self.confirm(session)
            if is_negative(text):
                session.history.append({"role": "user", "content": text})
                return self.decline(session)
            session.pending = None  # the patient moved on; never confirm a stale proposal later

        if is_medical_advice_request(text):
            return self._remember(session, text, Reply(ADVICE_REFUSAL, "refusal"))

        session.history.append({"role": "user", "content": text})
        return self._run_model(session)

    def _run_model(self, session: Session) -> Reply:
        tools_called: list[str] = []
        system = {"role": "system",
                  "content": build_system_prompt(self.toolbox.clock(), self.timezone, session.handle)}
        final, kind = TOO_MANY_STEPS, "error"
        for _ in range(self.max_steps):
            try:
                turn = self.model.complete([system, *session.history], self.toolbox.schemas())
            except LLMError:
                session.pending = None
                return self._remember(session, None, Reply(UNAVAILABLE, "error", tools_called))
            if not turn.tool_calls:
                final, kind = (turn.text.strip() or "How can I help with your appointment?"), "answer"
                break
            session.history.append({"role": "assistant", "content": turn.text, "tool_calls": list(turn.tool_calls)})
            for call in turn.tool_calls:
                result = self.toolbox.execute(session, call)
                tools_called.append(call.name)
                session.history.append(to_tool_message(call, result))
                if call.name == "triage_symptoms" and result.get("emergency"):
                    session.pending = None
                    return self._remember(session, None, Reply(result["message"], "emergency", tools_called))
        else:
            session.pending = None

        if "triage_symptoms" in tools_called and TRIAGE_DISCLAIMER not in final:
            final = f"{final}\n\n{TRIAGE_DISCLAIMER}"
        if session.pending is not None and kind == "answer":
            final = (f"{final}\n\nPlease confirm: {session.pending.summary}. "
                     "Reply 'yes' to confirm or 'no' to keep things as they are.")
            kind = "confirm"
        return self._remember(session, None, Reply(final, kind, tools_called))
