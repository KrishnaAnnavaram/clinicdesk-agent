"""Problem 4: read paths are read-only and never expose other patients."""

import json
import sqlite3
from datetime import date, time

import pytest

from clinicdesk_agent.agent.llm import ToolCall
from clinicdesk_agent.agent.tools import TOOL_SPECS, Session
from clinicdesk_agent.dates import DateRange
from clinicdesk_agent.scheduling.slots import find_doctors, search_open_slots
from tests.conftest import NOW


def test_reader_connection_cannot_write(db):
    with db.reader() as conn, pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM slots")


def test_search_filters(db):
    with db.reader() as conn:
        all_open = search_open_slots(conn, now=NOW)
        assert [s.slot_id for s in all_open] == [1, 3, 2, 4]  # past slot 5 excluded, ordered by time
        derm = search_open_slots(conn, now=NOW, specialty="dermatology")
        assert {s.slot_id for s in derm} == {3, 4}
        jan7 = search_open_slots(conn, now=NOW, date_range=DateRange.single(date(2026, 1, 7)))
        assert [s.slot_id for s in jan7] == [4]
        afternoon = search_open_slots(conn, now=NOW, window=(time(12), time(17)))
        assert [s.slot_id for s in afternoon] == [2]


def test_doctor_name_matching_ignores_title(db):
    with db.reader() as conn:
        assert [d.name for d in find_doctors(conn, name_query="dr. test skin")] == ["Dr. Test Skin"]
        assert [d.name for d in find_doctors(conn, name_query="Heart")] == ["Dr. Test Heart"]


def test_booked_slots_disappear_and_reveal_no_patient(desk, patients):
    a, b = patients
    desk.bookings.book(a.patient_id, 1)
    result = desk.toolbox.execute(Session(b.patient_id, b.handle),
                                  ToolCall("c1", "search_slots", {"specialty": "Cardiology"}))
    assert [s["slot_id"] for s in result["slots"]] == [2]
    blob = json.dumps(result)
    assert "patient-a" not in blob and "patient_id" not in blob


def test_no_tool_accepts_patient_id_or_sql():
    for spec in TOOL_SPECS:
        names = {p.name for p in spec.params}
        assert "patient_id" not in names
        assert not any("sql" in n or "query" in n for n in names)
        assert spec.schema()["parameters"]["additionalProperties"] is False


def test_injected_patient_id_argument_is_rejected(desk, patients):
    a, b = patients
    booking = desk.bookings.book(a.patient_id, 1)
    session_b = Session(b.patient_id, b.handle)
    result = desk.toolbox.execute(session_b, ToolCall("c1", "list_my_appointments", {"patient_id": a.patient_id}))
    assert result == {"ok": False, "error": "invalid_arguments", "message": result["message"]}
    result = desk.toolbox.execute(session_b, ToolCall("c2", "request_cancellation", {"booking_id": booking.booking_id}))
    assert result["ok"] is False and result["error"] == "booking_not_found"
    assert session_b.pending is None


def test_my_appointments_only_lists_own(desk, patients):
    a, b = patients
    desk.bookings.book(a.patient_id, 1)
    desk.bookings.book(b.patient_id, 3)
    result = desk.toolbox.execute(Session(a.patient_id, a.handle), ToolCall("c", "list_my_appointments", {}))
    assert [x["slot_id"] for x in result["appointments"]] == [1]
