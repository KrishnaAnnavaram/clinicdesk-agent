"""Typed scheduling errors. Each has a stable ``code`` that tools can return to the model."""


class SchedulingError(Exception):
    code = "scheduling_error"


class SlotNotFound(SchedulingError):
    code = "slot_not_found"


class SlotUnavailable(SchedulingError):
    code = "slot_unavailable"


class SlotInPast(SchedulingError):
    code = "slot_in_past"


class BookingNotFound(SchedulingError):
    """Also raised when the booking exists but belongs to someone else, so ids cannot be probed."""

    code = "booking_not_found"


class BookingLimitReached(SchedulingError):
    code = "booking_limit_reached"


class PatientConflict(SchedulingError):
    code = "patient_time_conflict"


class IdempotencyConflict(SchedulingError):
    code = "idempotency_conflict"


class AuthError(SchedulingError):
    code = "auth_error"
