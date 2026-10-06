"""Read-only queries: doctors, specialties and open slots.

Every function takes a connection from :meth:`Database.reader`, uses bound
parameters only, and never selects anything from ``patients`` or ``bookings``.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, time, timedelta

from clinicdesk_agent.dates import DateRange
from clinicdesk_agent.scheduling.models import Doctor, SlotView, from_db_time, to_db_time

MAX_SEARCH_RESULTS = 20

_SLOT_COLUMNS = """
    s.slot_id, s.doctor_id, d.name AS doctor_name, d.specialty, s.start_at, s.duration_min, s.is_booked
"""


def _row_to_slot(row: sqlite3.Row) -> SlotView:
    return SlotView(
        slot_id=int(row["slot_id"]),
        doctor_id=int(row["doctor_id"]),
        doctor_name=row["doctor_name"],
        specialty=row["specialty"],
        start_at=from_db_time(row["start_at"]),
        duration_min=int(row["duration_min"]),
        is_booked=bool(row["is_booked"]),
    )


def normalise_doctor_name(name: str) -> str:
    value = " ".join(name.lower().replace(".", " ").split())
    if value.startswith("dr "):
        value = value[3:]
    elif value.startswith("doctor "):
        value = value[7:]
    return value


def list_specialties(conn: sqlite3.Connection) -> list[str]:
    return [r["specialty"] for r in conn.execute("SELECT DISTINCT specialty FROM doctors ORDER BY specialty")]


def find_doctors(conn: sqlite3.Connection, *, specialty: str | None = None,
                 name_query: str | None = None) -> list[Doctor]:
    sql = "SELECT doctor_id, name, specialty FROM doctors WHERE 1 = 1"
    params: list[object] = []
    if specialty:
        sql += " AND lower(specialty) = lower(?)"
        params.append(specialty.strip())
    sql += " ORDER BY name"
    doctors = [Doctor(int(r["doctor_id"]), r["name"], r["specialty"]) for r in conn.execute(sql, params)]
    if name_query:
        needle = normalise_doctor_name(name_query)
        doctors = [d for d in doctors if needle and needle in normalise_doctor_name(d.name)]
    return doctors


def get_slot(conn: sqlite3.Connection, slot_id: int) -> SlotView | None:
    row = conn.execute(
        f"SELECT {_SLOT_COLUMNS} FROM slots s JOIN doctors d ON d.doctor_id = s.doctor_id WHERE s.slot_id = ?",
        (int(slot_id),),
    ).fetchone()
    return _row_to_slot(row) if row else None


def search_open_slots(
    conn: sqlite3.Connection,
    *,
    now: datetime,
    specialty: str | None = None,
    doctor_ids: list[int] | None = None,
    date_range: DateRange | None = None,
    window: tuple[time, time] | None = None,
    limit: int = 10,
) -> list[SlotView]:
    """Free slots strictly in the future, earliest first."""
    limit = max(1, min(int(limit), MAX_SEARCH_RESULTS))
    sql = [f"SELECT {_SLOT_COLUMNS} FROM slots s JOIN doctors d ON d.doctor_id = s.doctor_id",
           "WHERE s.is_booked = 0 AND s.start_at > ?"]
    params: list[object] = [to_db_time(now)]
    if specialty:
        sql.append("AND lower(d.specialty) = lower(?)")
        params.append(specialty.strip())
    if doctor_ids is not None:
        if not doctor_ids:
            return []
        sql.append(f"AND s.doctor_id IN ({', '.join('?' for _ in doctor_ids)})")
        params.extend(int(i) for i in doctor_ids)
    if date_range is not None:
        sql.append("AND s.start_at >= ? AND s.start_at < ?")
        params.append(to_db_time(datetime.combine(date_range.start, time.min)))
        params.append(to_db_time(datetime.combine(date_range.end + timedelta(days=1), time.min)))
    if window is not None:
        # start_at is 'YYYY-MM-DDTHH:MM', so the clock part is substr(start_at, 12, 5).
        sql.append("AND substr(s.start_at, 12, 5) >= ? AND substr(s.start_at, 12, 5) < ?")
        params.extend([window[0].strftime("%H:%M"), window[1].strftime("%H:%M")])
    sql.append("ORDER BY s.start_at, d.name LIMIT ?")
    params.append(limit)
    return [_row_to_slot(r) for r in conn.execute("\n".join(sql), params)]
