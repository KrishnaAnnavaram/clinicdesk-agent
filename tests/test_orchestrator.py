"""Problems 6 and 9: robust tool-calling loop, confirmation step, safety short-circuits."""

from clinicdesk_agent.agent.llm import AssistantTurn, LLMError, ScriptedChatModel, ToolCall
from clinicdesk_agent.agent.orchestrator import Orchestrator, is_affirmative, is_negative
from clinicdesk_agent.safety import TRIAGE_DISCLAIMER


def _orchestrator(desk, script, **kwargs):
    model = ScriptedChatModel(script)
    return Orchestrator(model, desk.toolbox, **kwargs), model


def test_multi_step_tool_use_then_answer(desk, session_a):
    orch, model = _orchestrator(desk, [
        AssistantTurn(tool_calls=(ToolCall("1", "list_specialties", {}),)),
        AssistantTurn(tool_calls=(ToolCall("2", "search_slots", {"specialty": "Cardiology"}),)),
        AssistantTurn(text="Slot 1 is free. None of the afternoon slots suit you?"),  # contains 'None'
    ])
    reply = orch.handle(session_a, "what cardiology slots are there")
    assert reply.kind == "answer"
    assert reply.tools_called == ["list_specialties", "search_slots"]
    assert "None of the afternoon" in reply.text
    assert len(model.calls) == 3
    # the model saw the tool results as tool messages
    assert [m["role"] for m in model.calls[-1]][-2:] == ["assistant", "tool"]


def test_unknown_tool_and_bad_json_are_reported_back_not_raised(desk, session_a):
    orch, model = _orchestrator(desk, [
        AssistantTurn(tool_calls=(ToolCall("1", "run_sql", {"sql": "DELETE FROM slots"}),
                                  ToolCall("2", "request_booking", None, raw_arguments="{oops"))),
        AssistantTurn(text="Sorry, let me try again."),
    ])
    reply = orch.handle(session_a, "book something")
    assert reply.kind == "answer"
    tool_messages = [m for m in session_a.history if m["role"] == "tool"]
    assert '"unknown_tool"' in tool_messages[0]["content"]
    assert '"invalid_arguments"' in tool_messages[1]["content"]


def test_model_failure_becomes_friendly_message(desk, session_a):
    orch, _ = _orchestrator(desk, [LLMError("timeout")])
    reply = orch.handle(session_a, "find me a slot")
    assert reply.kind == "error" and "Nothing was booked" in reply.text


def test_step_limit_stops_runaway_loops(desk, session_a):
    looping = lambda messages, tools: AssistantTurn(tool_calls=(ToolCall("x", "list_specialties", {}),))  # noqa: E731
    orch, model = _orchestrator(desk, looping, max_steps=3)
    reply = orch.handle(session_a, "hi")
    assert reply.kind == "error" and len(model.calls) == 3


def test_booking_requires_explicit_confirmation(desk, session_a):
    orch, _ = _orchestrator(desk, [
        AssistantTurn(tool_calls=(ToolCall("1", "request_booking", {"slot_id": 1}),)),
        AssistantTurn(text="Great, booked!"),  # the model claims success prematurely
    ])
    reply = orch.handle(session_a, "book slot 1")
    assert reply.kind == "confirm" and "Please confirm" in reply.text
    assert desk.bookings.list_for_patient(session_a.patient_id) == []
    done = orch.handle(session_a, "yes")
    assert done.kind == "done" and "Booked" in done.text
    assert len(desk.bookings.list_for_patient(session_a.patient_id)) == 1


def test_decline_and_stale_confirmation(desk, session_a):
    orch, _ = _orchestrator(desk, [
        AssistantTurn(tool_calls=(ToolCall("1", "request_booking", {"slot_id": 1}),)),
        AssistantTurn(text="Shall I?"),
        AssistantTurn(text="We offer cardiology."),
        AssistantTurn(text="Yes to what?"),
    ])
    orch.handle(session_a, "book slot 1")
    orch.handle(session_a, "what specialties do you have")  # moves on -> proposal dropped
    assert session_a.pending is None
    orch.handle(session_a, "yes")
    assert desk.bookings.list_for_patient(session_a.patient_id) == []


def test_emergency_never_reaches_the_model(desk, session_a):
    orch, model = _orchestrator(desk, [])
    reply = orch.handle(session_a, "my dad has slurred speech and his face is drooping")
    assert reply.kind == "emergency" and "911" in reply.text
    assert model.calls == []


def test_emergency_inside_triage_tool(desk, session_a):
    orch, _ = _orchestrator(desk, [
        AssistantTurn(tool_calls=(ToolCall("1", "triage_symptoms", {"symptoms": "he fainted twice"}),)),
    ])
    reply = orch.handle(session_a, "symptoms are in the attached note")
    assert reply.kind == "emergency"


def test_prescription_request_is_refused_without_model(desk, session_a):
    orch, model = _orchestrator(desk, [])
    reply = orch.handle(session_a, "Which antibiotic should I take?")
    assert reply.kind == "refusal" and model.calls == []


def test_triage_reply_always_carries_disclaimer(desk, session_a):
    orch, _ = _orchestrator(desk, [
        AssistantTurn(tool_calls=(ToolCall("1", "triage_symptoms", {"symptoms": "itchy rash"}),)),
        AssistantTurn(text="You should see a dermatologist."),
    ])
    reply = orch.handle(session_a, "I have an itchy rash")
    assert TRIAGE_DISCLAIMER in reply.text


def test_history_is_trimmed_at_user_boundaries(desk, session_a):
    orch, _ = _orchestrator(desk, lambda m, t: AssistantTurn(text="ok"), history_limit=6)
    for i in range(10):
        orch.handle(session_a, f"message {i}")
    assert len(session_a.history) <= 6 and session_a.history[0]["role"] == "user"


def test_yes_no_detection():
    assert is_affirmative("Yes please") and is_affirmative("ok") and not is_affirmative("yesterday I fell")
    assert is_negative("no thanks") and not is_affirmative("no")
