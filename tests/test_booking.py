"""Problems 1 and 2: double booking and booking outside published availability."""

import sqlite3
import threading

import pytest

from clinicdesk_agent.db import transaction
from clinicdesk_agent.scheduling import BookingService, check_invariants
from clinicdesk_agent.scheduling import errors
from tests.conftest import NOW


def _slot_count(db):
    with db.reader() as conn:
        return conn.execute("SELECT COUNT(*) FROM slots").fetchone()[0]


def test_book_open_slot(desk, patients):
    a, _ = patients
    booking = desk.bookings.book(a.patient_id, 1)
    assert booking.status == "active" and booking.slot_id == 1
    assert booking.doctor_name == "Dr. Test Heart"
    assert check_invariants(desk.db) == []


def test_second_patient_cannot_overwrite_existing_booking(desk, patients):
    a, b = patients
    desk.bookings.book(a.patient_id, 1)
    with pytest.raises(errors.SlotUnavailable):
        desk.bookings.book(b.patient_id, 1)
    # the first patient's booking is untouched
    assert [x.slot_id for x in desk.bookings.list_for_patient(a.patient_id)] == [1]
    assert desk.bookings.list_for_patient(b.patient_id) == []


def test_unknown_slot_is_rejected_and_nothing_is_inserted(desk, patients):
    a, _ = patients
    before = _slot_count(desk.db)
    with pytest.raises(errors.SlotNotFound):
        desk.bookings.book(a.patient_id, 999)
    assert _slot_count(desk.db) == before
    assert desk.bookings.list_for_patient(a.patient_id) == []


def test_past_slot_cannot_be_booked(desk, patients):
    a, _ = patients
    with pytest.raises(errors.SlotInPast):
        desk.bookings.book(a.patient_id, 5)


def test_database_rejects_two_active_bookings_for_one_slot(desk, patients):
    a, b = patients
    desk.bookings.book(a.patient_id, 1)
    with desk.db.writer() as conn, pytest.raises(sqlite3.IntegrityError):
        with transaction(conn):
            conn.execute("INSERT INTO bookings (slot_id, patient_id, status, created_at) "
                         "VALUES (1, ?, 'active', '2026-01-05T08:00')", (b.patient_id,))


def test_database_rejects_duplicate_doctor_slot(desk):
    with desk.db.writer() as conn, pytest.raises(sqlite3.IntegrityError):
        with transaction(conn):
            conn.execute("INSERT INTO slots (doctor_id, start_at, duration_min) VALUES (1, '2026-01-06T09:00', 30)")


def test_concurrent_bookers_get_exactly_one_success(desk, clock):
    ids = [desk.patients.register(f"racer-{i}", "passcode-xyz", now=NOW).patient_id for i in range(6)]
    outcomes: list[str] = []
    barrier = threading.Barrier(len(ids))

    def attempt(patient_id: int) -> None:
        service = BookingService(desk.db, clock)  # separate connections per thread
        barrier.wait()
        try:
            service.book(patient_id, 2)
            outcomes.append("ok")
        except errors.SlotUnavailable:
            outcomes.append("taken")

    threads = [threading.Thread(target=attempt, args=(pid,)) for pid in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["ok"] + ["taken"] * (len(ids) - 1)
    assert check_invariants(desk.db) == []


def test_idempotent_retry_returns_same_booking(desk, patients):
    a, _ = patients
    first = desk.bookings.book(a.patient_id, 1, idempotency_key="k-1")
    again = desk.bookings.book(a.patient_id, 1, idempotency_key="k-1")
    assert again.booking_id == first.booking_id
    assert len(desk.bookings.list_for_patient(a.patient_id)) == 1


def test_idempotency_key_cannot_be_reused_for_other_slot(desk, patients):
    a, _ = patients
    desk.bookings.book(a.patient_id, 1, idempotency_key="k-2")
    with pytest.raises(errors.IdempotencyConflict):
        desk.bookings.book(a.patient_id, 3, idempotency_key="k-2")


def test_patient_cannot_hold_two_appointments_at_same_time(desk, patients):
    a, _ = patients
    desk.bookings.book(a.patient_id, 1)  # 2026-01-06 09:00 cardiology
    with pytest.raises(errors.PatientConflict):
        desk.bookings.book(a.patient_id, 3)  # 2026-01-06 09:00 dermatology


def test_active_booking_limit(desk, patients, clock):
    a, _ = patients
    service = BookingService(desk.db, clock, max_active_bookings=1)
    service.book(a.patient_id, 1)
    with pytest.raises(errors.BookingLimitReached):
        service.book(a.patient_id, 4)


def test_cancel_frees_slot_for_others(desk, patients):
    a, b = patients
    booking = desk.bookings.book(a.patient_id, 1)
    desk.bookings.cancel(a.patient_id, booking.booking_id)
    assert desk.bookings.book(b.patient_id, 1).patient_id == b.patient_id
    assert check_invariants(desk.db) == []


def test_other_patient_cannot_cancel_or_see_booking(desk, patients):
    a, b = patients
    booking = desk.bookings.book(a.patient_id, 1)
    with pytest.raises(errors.BookingNotFound):
        desk.bookings.cancel(b.patient_id, booking.booking_id)
    assert desk.bookings.list_for_patient(b.patient_id) == []


def test_reschedule_is_atomic(desk, patients):
    a, b = patients
    mine = desk.bookings.book(a.patient_id, 1)
    desk.bookings.book(b.patient_id, 4)
    with pytest.raises(errors.SlotUnavailable):
        desk.bookings.reschedule(a.patient_id, mine.booking_id, 4)
    # failed move leaves the original booking in place
    assert [x.slot_id for x in desk.bookings.list_for_patient(a.patient_id)] == [1]
    moved = desk.bookings.reschedule(a.patient_id, mine.booking_id, 2)
    assert moved.slot_id == 2
    assert [x.slot_id for x in desk.bookings.list_for_patient(a.patient_id)] == [2]
    assert check_invariants(desk.db) == []
