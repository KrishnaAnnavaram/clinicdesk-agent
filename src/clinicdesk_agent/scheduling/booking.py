"""Transactional booking, cancellation and rescheduling.

Rules enforced here (and backed by database constraints):

* A booking always references an existing slot id; there is no code path that
  creates a slot on demand, so nobody is booked outside published availability.
* A slot is claimed with a conditional ``UPDATE ... WHERE is_booked = 0`` inside
  ``BEGIN IMMEDIATE``; if another booking won the race, nothing is overwritten.
* Slots in the past cannot be booked.
* Patients only see, cancel or move their own bookings.
* An optional idempotency key makes a retried request return the original booking.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime
from typing import Callable

from clinicdesk_agent.db import Database, transaction
from clinicdesk_agent.scheduling import errors
from clinicdesk_agent.scheduling.models import Booking, from_db_time, to_db_time
from clinicdesk_agent.scheduling.slots import get_slot

Clock = Callable[[], datetime]

_BOOKING_SELECT = """
SELECT b.booking_id, b.slot_id, b.patient_id, b.status, d.name AS doctor_name, d.specialty,
       s.start_at, s.duration_min
FROM bookings b
JOIN slots s ON s.slot_id = b.slot_id
JOIN doctors d ON d.doctor_id = s.doctor_id
"""


def _row_to_booking(row: sqlite3.Row) -> Booking:
    return Booking(
        booking_id=int(row["booking_id"]),
        slot_id=int(row["slot_id"]),
        patient_id=int(row["patient_id"]),
        status=row["status"],
        doctor_name=row["doctor_name"],
        specialty=row["specialty"],
        start_at=from_db_time(row["start_at"]),
        duration_min=int(row["duration_min"]),
    )


class BookingService:
    def __init__(self, db: Database, clock: Clock, *, max_active_bookings: int = 3) -> None:
        self.db = db
        self.clock = clock
        self.max_active_bookings = max_active_bookings

    # ------------------------------------------------------------------ queries
    def list_for_patient(self, patient_id: int, *, include_past: bool = False) -> list[Booking]:
        sql = _BOOKING_SELECT + " WHERE b.patient_id = ? AND b.status = 'active'"
        params: list[object] = [int(patient_id)]
        if not include_past:
            sql += " AND s.start_at > ?"
            params.append(to_db_time(self.clock()))
        sql += " ORDER BY s.start_at"
        with self.db.reader() as conn:
            return [_row_to_booking(r) for r in conn.execute(sql, params)]

    def _owned_active_booking(self, conn: sqlite3.Connection, patient_id: int, booking_id: int) -> Booking:
        row = conn.execute(
            _BOOKING_SELECT + " WHERE b.booking_id = ? AND b.patient_id = ? AND b.status = 'active'",
            (int(booking_id), int(patient_id)),
        ).fetchone()
        if row is None:
            raise errors.BookingNotFound(f"no active booking {booking_id} for this patient")
        return _row_to_booking(row)

    # ------------------------------------------------------------------ writes
    def _claim_slot(self, conn: sqlite3.Connection, patient_id: int, slot_id: int, now: datetime,
                    *, ignore_booking_id: int | None = None) -> None:
        slot = get_slot(conn, slot_id)
        if slot is None:
            raise errors.SlotNotFound(f"slot {slot_id} does not exist")
        if slot.start_at <= now:
            raise errors.SlotInPast(f"slot {slot_id} has already started")
        clash = conn.execute(
            "SELECT b.booking_id FROM bookings b JOIN slots s ON s.slot_id = b.slot_id "
            "WHERE b.patient_id = ? AND b.status = 'active' AND s.start_at = ? AND b.booking_id IS NOT ?",
            (int(patient_id), to_db_time(slot.start_at), ignore_booking_id),
        ).fetchone()
        if clash:
            raise errors.PatientConflict("you already have an appointment at that time")
        claimed = conn.execute(
            "UPDATE slots SET is_booked = 1, version = version + 1 WHERE slot_id = ? AND is_booked = 0",
            (int(slot_id),),
        )
        if claimed.rowcount != 1:
            raise errors.SlotUnavailable(f"slot {slot_id} is already booked")

    def book(self, patient_id: int, slot_id: int, *, idempotency_key: str | None = None) -> Booking:
        now = self.clock()
        with self.db.writer() as conn, transaction(conn):
            if idempotency_key:
                existing = conn.execute(_BOOKING_SELECT + " WHERE b.idempotency_key = ?",
                                        (idempotency_key,)).fetchone()
                if existing is not None:
                    booking = _row_to_booking(existing)
                    if booking.patient_id != int(patient_id) or booking.slot_id != int(slot_id):
                        raise errors.IdempotencyConflict("idempotency key reused for a different request")
                    return booking
            active = conn.execute(
                "SELECT COUNT(*) FROM bookings b JOIN slots s ON s.slot_id = b.slot_id "
                "WHERE b.patient_id = ? AND b.status = 'active' AND s.start_at > ?",
                (int(patient_id), to_db_time(now)),
            ).fetchone()[0]
            if active >= self.max_active_bookings:
                raise errors.BookingLimitReached(
                    f"you already have {active} upcoming appointments (limit {self.max_active_bookings})")
            self._claim_slot(conn, patient_id, slot_id, now)
            cur = conn.execute(
                "INSERT INTO bookings (slot_id, patient_id, status, idempotency_key, created_at) "
                "VALUES (?, ?, 'active', ?, ?)",
                (int(slot_id), int(patient_id), idempotency_key, to_db_time(now)),
            )
            row = conn.execute(_BOOKING_SELECT + " WHERE b.booking_id = ?", (cur.lastrowid,)).fetchone()
            return _row_to_booking(row)

    def cancel(self, patient_id: int, booking_id: int) -> Booking:
        now = self.clock()
        with self.db.writer() as conn, transaction(conn):
            booking = self._owned_active_booking(conn, patient_id, booking_id)
            if booking.start_at <= now:
                raise errors.SlotInPast("past appointments cannot be cancelled")
            conn.execute("UPDATE bookings SET status = 'cancelled', cancelled_at = ? WHERE booking_id = ?",
                         (to_db_time(now), booking.booking_id))
            conn.execute("UPDATE slots SET is_booked = 0, version = version + 1 WHERE slot_id = ?",
                         (booking.slot_id,))
        return replace(booking, status="cancelled")

    def reschedule(self, patient_id: int, booking_id: int, new_slot_id: int) -> Booking:
        """Move a booking to another slot atomically: either both changes happen or neither does."""
        now = self.clock()
        with self.db.writer() as conn, transaction(conn):
            old = self._owned_active_booking(conn, patient_id, booking_id)
            if old.start_at <= now:
                raise errors.SlotInPast("past appointments cannot be moved")
            if old.slot_id == int(new_slot_id):
                return old
            self._claim_slot(conn, patient_id, new_slot_id, now, ignore_booking_id=old.booking_id)
            conn.execute("UPDATE bookings SET status = 'cancelled', cancelled_at = ? WHERE booking_id = ?",
                         (to_db_time(now), old.booking_id))
            conn.execute("UPDATE slots SET is_booked = 0, version = version + 1 WHERE slot_id = ?", (old.slot_id,))
            cur = conn.execute(
                "INSERT INTO bookings (slot_id, patient_id, status, created_at) VALUES (?, ?, 'active', ?)",
                (int(new_slot_id), int(patient_id), to_db_time(now)),
            )
            row = conn.execute(_BOOKING_SELECT + " WHERE b.booking_id = ?", (cur.lastrowid,)).fetchone()
            return _row_to_booking(row)


def check_invariants(db: Database) -> list[str]:
    """Return a list of human-readable invariant violations (empty when consistent)."""
    problems: list[str] = []
    with db.reader() as conn:
        for row in conn.execute(
            "SELECT slot_id, COUNT(*) AS n FROM bookings WHERE status = 'active' GROUP BY slot_id HAVING n > 1"
        ):
            problems.append(f"slot {row['slot_id']} has {row['n']} active bookings")
        for row in conn.execute(
            "SELECT s.slot_id FROM slots s LEFT JOIN bookings b ON b.slot_id = s.slot_id AND b.status = 'active' "
            "WHERE (s.is_booked = 1 AND b.booking_id IS NULL) OR (s.is_booked = 0 AND b.booking_id IS NOT NULL)"
        ):
            problems.append(f"slot {row['slot_id']} booked flag disagrees with bookings")
        for row in conn.execute(
            "SELECT doctor_id, start_at, COUNT(*) AS n FROM slots GROUP BY doctor_id, start_at HAVING n > 1"
        ):
            problems.append(f"doctor {row['doctor_id']} has duplicate slots at {row['start_at']}")
    return problems
