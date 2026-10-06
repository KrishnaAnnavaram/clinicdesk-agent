"""Plain data objects returned by the scheduling service.

None of these carry another patient's identity: a :class:`SlotView` only says
whether a slot is free, and a :class:`Booking` is only ever returned to the
patient who owns it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

TIME_FORMAT = "%Y-%m-%dT%H:%M"


def to_db_time(value: datetime) -> str:
    return value.strftime(TIME_FORMAT)


def from_db_time(value: str) -> datetime:
    return datetime.strptime(value, TIME_FORMAT)


def describe_time(value: datetime) -> str:
    """Human-friendly, unambiguous: 'Tue 14 Oct 2026, 09:30'."""
    return value.strftime("%a %d %b %Y, %H:%M")


@dataclass(frozen=True)
class Doctor:
    doctor_id: int
    name: str
    specialty: str


@dataclass(frozen=True)
class SlotView:
    slot_id: int
    doctor_id: int
    doctor_name: str
    specialty: str
    start_at: datetime
    duration_min: int
    is_booked: bool

    def to_public_dict(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "doctor": self.doctor_name,
            "specialty": self.specialty,
            "start": to_db_time(self.start_at),
            "when": describe_time(self.start_at),
            "duration_min": self.duration_min,
        }


@dataclass(frozen=True)
class Booking:
    booking_id: int
    slot_id: int
    patient_id: int
    status: str
    doctor_name: str
    specialty: str
    start_at: datetime
    duration_min: int

    def to_owner_dict(self) -> dict:
        """Representation shown to the owning patient (no internal patient id)."""
        return {
            "booking_id": self.booking_id,
            "slot_id": self.slot_id,
            "status": self.status,
            "doctor": self.doctor_name,
            "specialty": self.specialty,
            "start": to_db_time(self.start_at),
            "when": describe_time(self.start_at),
            "duration_min": self.duration_min,
        }


@dataclass(frozen=True)
class Patient:
    patient_id: int
    handle: str
