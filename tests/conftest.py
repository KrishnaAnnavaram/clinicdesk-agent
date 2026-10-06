from datetime import date, datetime, time

import pytest

from clinicdesk_agent.agent.tools import Session
from clinicdesk_agent.app import build_clinic_desk
from clinicdesk_agent.config import Settings
from clinicdesk_agent.db import Database, transaction

TODAY = date(2026, 1, 5)  # Monday
NOW = datetime.combine(TODAY, time(8, 0))


class FakeClock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def db(tmp_path):
    """Tiny hand-written fixture: 2 doctors, 4 future slots and 1 past slot."""
    database = Database(tmp_path / "test.db")
    database.initialise()
    with database.writer() as conn, transaction(conn):
        conn.execute("INSERT INTO doctors (doctor_id, name, specialty) VALUES (1, 'Dr. Test Heart', 'Cardiology')")
        conn.execute("INSERT INTO doctors (doctor_id, name, specialty) VALUES (2, 'Dr. Test Skin', 'Dermatology')")
        rows = [
            (1, 1, "2026-01-06T09:00"), (2, 1, "2026-01-06T14:00"),
            (3, 2, "2026-01-06T09:00"), (4, 2, "2026-01-07T10:30"),
            (5, 1, "2026-01-04T09:00"),  # yesterday
        ]
        conn.executemany("INSERT INTO slots (slot_id, doctor_id, start_at, duration_min) VALUES (?, ?, ?, 30)", rows)
    return database


@pytest.fixture
def desk(db, clock, tmp_path):
    settings = Settings(db_path=db.path)
    return build_clinic_desk(settings, clock=clock)


@pytest.fixture
def patients(desk):
    a = desk.patients.register("patient-a", "passcode-a1", now=NOW)
    b = desk.patients.register("patient-b", "passcode-b2", now=NOW)
    return a, b


@pytest.fixture
def session_a(patients):
    a, _ = patients
    return Session(a.patient_id, a.handle)
