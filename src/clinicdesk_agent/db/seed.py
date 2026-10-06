"""Reproducible synthetic demo data with dates relative to "today".

* A fixed ``seed`` gives the same doctors, slots and bookings every run.
* ``reset=True`` wipes slots/bookings/patients first, so re-running never
  duplicates anything; doctors are upserted by their unique name.
* Each doctor gets a set of *distinct* start times per day (no duplicate slots).
* Pre-booked slots belong to synthetic demo patients ``demo-patient-a`` ...,
  whose passcodes are random and never printed (they exist only to occupy slots).
"""

from __future__ import annotations

import random
import secrets
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from clinicdesk_agent.db.connection import Database, transaction
from clinicdesk_agent.safety.triage import SPECIALTIES
from clinicdesk_agent.scheduling.models import to_db_time
from clinicdesk_agent.scheduling.patients import hash_passcode

_GIVEN = ["Avery", "Jordan", "Riley", "Morgan", "Casey", "Quinn", "Rowan", "Sasha", "Emerson", "Hayden",
          "Parker", "Reese", "Skyler", "Dakota", "Finley", "Harper", "Kendall", "Logan", "Marlowe", "Tatum"]
_FAMILY = ["Okafor", "Lindqvist", "Moreau", "Tanaka", "Castillo", "Novak", "Haddad", "Petrov", "Achebe",
           "Fischer", "Sato", "Delgado", "Nakamura", "Kowalski", "Mensah", "Oyelaran", "Varga", "Ibsen"]

SESSION_STARTS = {
    "morning": [time(9, 0), time(9, 30), time(10, 0), time(10, 30), time(11, 0), time(11, 30)],
    "afternoon": [time(13, 0), time(13, 30), time(14, 0), time(14, 30), time(15, 0), time(15, 30), time(16, 0)],
}


@dataclass(frozen=True)
class SeedSummary:
    doctors: int
    slots: int
    booked: int
    first_day: date
    last_day: date


def _doctor_names(rng: random.Random, count: int) -> list[str]:
    pairs = [(g, f) for g in _GIVEN for f in _FAMILY]
    rng.shuffle(pairs)
    return [f"Dr. {g} {f}" for g, f in pairs[:count]]


def seed_database(
    db: Database,
    *,
    seed: int = 7,
    today: date | None = None,
    days: int = 14,
    doctors_per_specialty: int = 2,
    slot_minutes: int = 30,
    booked_fraction: float = 0.25,
    reset: bool = True,
) -> SeedSummary:
    if days < 1 or doctors_per_specialty < 1 or not 0 <= booked_fraction < 1:
        raise ValueError("invalid seed parameters")
    today = today or date.today()
    rng = random.Random(seed)
    db.initialise()

    names = _doctor_names(rng, len(SPECIALTIES) * doctors_per_specialty)
    roster = [(names[i * doctors_per_specialty + j], spec)
              for i, spec in enumerate(SPECIALTIES) for j in range(doctors_per_specialty)]

    first_day = today + timedelta(days=1)
    with db.writer() as conn, transaction(conn):
        if reset:
            conn.execute("DELETE FROM bookings")
            conn.execute("DELETE FROM slots")
            conn.execute("DELETE FROM patients")
            conn.execute("DELETE FROM doctors")
        for name, specialty in roster:
            conn.execute("INSERT INTO doctors (name, specialty) VALUES (?, ?) "
                         "ON CONFLICT(name) DO UPDATE SET specialty = excluded.specialty", (name, specialty))
        doctor_ids = [r[0] for r in conn.execute("SELECT doctor_id FROM doctors ORDER BY doctor_id")]

        demo_patients = []
        for letter in "abcde":
            handle = f"demo-patient-{letter}"
            conn.execute(
                "INSERT INTO patients (handle, passcode_hash, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(handle) DO NOTHING",
                (handle, hash_passcode(secrets.token_urlsafe(16)), to_db_time(datetime.now())),
            )
            row = conn.execute("SELECT patient_id FROM patients WHERE handle = ?", (handle,)).fetchone()
            demo_patients.append(row[0])

        slot_count = booked = 0
        for doctor_id in doctor_ids:
            for offset in range(days):
                day = first_day + timedelta(days=offset)
                if day.weekday() == 6:  # clinic closed on Sundays
                    continue
                sessions = rng.choice([["morning"], ["afternoon"], ["morning", "afternoon"]])
                starts = sorted({t for s in sessions for t in SESSION_STARTS[s]})
                chosen = sorted(rng.sample(starts, k=rng.randint(2, min(5, len(starts)))))
                for start in chosen:
                    is_booked = rng.random() < booked_fraction
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO slots (doctor_id, start_at, duration_min, is_booked) VALUES (?, ?, ?, ?)",
                        (doctor_id, to_db_time(datetime.combine(day, start)), slot_minutes, int(is_booked)),
                    )
                    if cur.rowcount != 1:
                        continue
                    slot_count += 1
                    if is_booked:
                        booked += 1
                        conn.execute(
                            "INSERT INTO bookings (slot_id, patient_id, status, created_at) VALUES (?, ?, 'active', ?)",
                            (cur.lastrowid, rng.choice(demo_patients), to_db_time(datetime.combine(today, time(8)))),
                        )
    return SeedSummary(len(doctor_ids), slot_count, booked, first_day, first_day + timedelta(days=days - 1))
