"""Problem 7: reproducible, duplicate-free seed data relative to today."""

from datetime import date

from clinicdesk_agent.db import Database
from clinicdesk_agent.db.seed import seed_database
from clinicdesk_agent.scheduling import check_invariants

TODAY = date(2026, 3, 2)


def _snapshot(db):
    with db.reader() as conn:
        doctors = conn.execute("SELECT name, specialty FROM doctors ORDER BY name").fetchall()
        slots = conn.execute("SELECT d.name, s.start_at, s.is_booked FROM slots s JOIN doctors d "
                             "USING (doctor_id) ORDER BY 1, 2").fetchall()
    return [tuple(r) for r in doctors], [tuple(r) for r in slots]


def test_same_seed_same_data(tmp_path):
    a, b = Database(tmp_path / "a.db"), Database(tmp_path / "b.db")
    seed_database(a, seed=3, today=TODAY, days=5)
    seed_database(b, seed=3, today=TODAY, days=5)
    assert _snapshot(a) == _snapshot(b)


def test_reseeding_does_not_duplicate(tmp_path):
    db = Database(tmp_path / "x.db")
    first = seed_database(db, seed=1, today=TODAY, days=4)
    second = seed_database(db, seed=1, today=TODAY, days=4)
    assert first.doctors == second.doctors == 20
    doctors, slots = _snapshot(db)
    assert len(doctors) == 20 and len(slots) == second.slots
    assert check_invariants(db) == []


def test_dates_are_relative_to_today_and_skip_sundays(tmp_path):
    db = Database(tmp_path / "y.db")
    summary = seed_database(db, seed=2, today=TODAY, days=7)
    assert summary.first_day == date(2026, 3, 3)
    _, slots = _snapshot(db)
    days = {date.fromisoformat(start[:10]) for _, start, _ in slots}
    assert min(days) > TODAY and max(days) <= summary.last_day
    assert all(d.weekday() != 6 for d in days)


def test_booked_slots_have_bookings_and_no_plain_passcodes(tmp_path):
    db = Database(tmp_path / "z.db")
    summary = seed_database(db, seed=5, today=TODAY, days=3, booked_fraction=0.5)
    assert summary.booked > 0
    assert check_invariants(db) == []
    with db.reader() as conn:
        hashes = [r[0] for r in conn.execute("SELECT passcode_hash FROM patients")]
    assert hashes and all(h.startswith("scrypt$") for h in hashes)
