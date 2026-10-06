"""Problem 5: tools receive the model's (validated) arguments, not some other message object."""

import pytest

from clinicdesk_agent.agent.llm import ToolCall
from clinicdesk_agent.agent.tools import SPEC_BY_NAME, ToolArgumentError, validate_arguments


def test_validate_coerces_and_rejects():
    spec = SPEC_BY_NAME["search_slots"]
    assert validate_arguments(spec, {"limit": "5", "part_of_day": "Morning"}) == {"limit": 5, "part_of_day": "morning"}
    with pytest.raises(ToolArgumentError):
        validate_arguments(spec, {"limit": 0})
    with pytest.raises(ToolArgumentError):
        validate_arguments(spec, {"part_of_day": "midnight"})
    with pytest.raises(ToolArgumentError):
        validate_arguments(spec, {"specialty": "x" * 1000})
    with pytest.raises(ToolArgumentError):
        validate_arguments(SPEC_BY_NAME["request_booking"], {})
    with pytest.raises(ToolArgumentError):
        validate_arguments(SPEC_BY_NAME["request_booking"], {"slot_id": True})
    with pytest.raises(ToolArgumentError):
        validate_arguments(SPEC_BY_NAME["request_booking"], None)  # un-parseable JSON from the model


def test_search_uses_the_arguments_it_was_given(desk, session_a):
    derm = desk.toolbox.execute(session_a, ToolCall("1", "search_slots", {"specialty": "Dermatology"}))
    cardio = desk.toolbox.execute(session_a, ToolCall("2", "search_slots", {"specialty": "Cardiology",
                                                                             "date": "tomorrow",
                                                                             "part_of_day": "afternoon"}))
    assert {s["specialty"] for s in derm["slots"]} == {"Dermatology"}
    assert [s["slot_id"] for s in cardio["slots"]] == [2]
    assert cardio["resolved_dates"] == {"from": "2026-01-06", "to": "2026-01-06"}


def test_search_reports_bad_inputs(desk, session_a):
    bad_date = desk.toolbox.execute(session_a, ToolCall("1", "search_slots", {"date": "the 45th"}))
    assert bad_date["error"] == "invalid_date"
    bad_spec = desk.toolbox.execute(session_a, ToolCall("2", "search_slots", {"specialty": "Astrology"}))
    assert bad_spec["error"] == "unknown_specialty" and "Cardiology" in bad_spec["specialties"]
    bad_doc = desk.toolbox.execute(session_a, ToolCall("3", "search_slots", {"doctor_name": "Nobody"}))
    assert bad_doc["error"] == "doctor_not_found"
    unknown = desk.toolbox.execute(session_a, ToolCall("4", "drop_table", {}))
    assert unknown["error"] == "unknown_tool"


def test_request_booking_only_proposes(desk, session_a):
    result = desk.toolbox.execute(session_a, ToolCall("1", "request_booking", {"slot_id": 1}))
    assert result["status"] == "awaiting_confirmation"
    assert session_a.pending is not None and session_a.pending.slot_id == 1
    assert desk.bookings.list_for_patient(session_a.patient_id) == []  # nothing written yet
    applied = desk.toolbox.apply_pending(session_a)
    assert applied["action"] == "booked" and session_a.pending is None
    assert len(desk.bookings.list_for_patient(session_a.patient_id)) == 1


def test_request_booking_rejects_taken_past_and_unknown(desk, patients, session_a):
    _, b = patients
    desk.bookings.book(b.patient_id, 3)
    for slot_id, code in [(3, "slot_unavailable"), (5, "slot_in_past"), (42, "slot_not_found")]:
        result = desk.toolbox.execute(session_a, ToolCall("x", "request_booking", {"slot_id": slot_id}))
        assert result["error"] == code
    assert session_a.pending is None


def test_slot_taken_between_proposal_and_confirmation(desk, patients, session_a):
    _, b = patients
    desk.toolbox.execute(session_a, ToolCall("1", "request_booking", {"slot_id": 1}))
    desk.bookings.book(b.patient_id, 1)  # someone else is faster
    result = desk.toolbox.apply_pending(session_a)
    assert result["ok"] is False and result["error"] == "slot_unavailable"
