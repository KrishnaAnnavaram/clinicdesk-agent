-- clinicdesk-agent schema (SQLite).
-- Invariants enforced by the database itself, in addition to the service layer:
--   * a doctor offers at most one slot per start time        (UNIQUE doctor_id, start_at)
--   * a slot has at most one active booking                  (partial UNIQUE index)
--   * bookings can only reference slots that exist           (foreign key)
-- Times are clinic-local wall-clock strings 'YYYY-MM-DDTHH:MM'.

CREATE TABLE IF NOT EXISTS doctors (
    doctor_id   INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    specialty   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS slots (
    slot_id      INTEGER PRIMARY KEY,
    doctor_id    INTEGER NOT NULL REFERENCES doctors (doctor_id),
    start_at     TEXT NOT NULL,
    duration_min INTEGER NOT NULL CHECK (duration_min BETWEEN 5 AND 240),
    is_booked    INTEGER NOT NULL DEFAULT 0 CHECK (is_booked IN (0, 1)),
    version      INTEGER NOT NULL DEFAULT 0,
    UNIQUE (doctor_id, start_at)
);

-- Data minimisation: a patient is a login handle plus a salted passcode hash.
-- No date of birth, phone number, address or symptoms are stored.
CREATE TABLE IF NOT EXISTS patients (
    patient_id    INTEGER PRIMARY KEY,
    handle        TEXT NOT NULL UNIQUE,
    passcode_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bookings (
    booking_id      INTEGER PRIMARY KEY,
    slot_id         INTEGER NOT NULL REFERENCES slots (slot_id),
    patient_id      INTEGER NOT NULL REFERENCES patients (patient_id),
    status          TEXT NOT NULL CHECK (status IN ('active', 'cancelled')),
    idempotency_key TEXT UNIQUE,
    created_at      TEXT NOT NULL,
    cancelled_at    TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_bookings_one_active_per_slot
    ON bookings (slot_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS ix_slots_start ON slots (start_at);
CREATE INDEX IF NOT EXISTS ix_bookings_patient ON bookings (patient_id, status);
