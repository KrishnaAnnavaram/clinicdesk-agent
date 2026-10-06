"""User-facing safety text. Kept in one place so it is reviewed once and reused everywhere."""

from __future__ import annotations

TRIAGE_DISCLAIMER = (
    "This is not medical advice or a diagnosis. The suggestion only helps you pick which kind of "
    "clinician to book. If your symptoms get worse or you are worried, contact a medical professional."
)

ADVICE_REFUSAL = (
    "I can't diagnose conditions, recommend medicines or give doses. A clinician can do that during an "
    "appointment. I can help you find and book one; tell me what kind of doctor or which day suits you."
)


def emergency_message(reason: str, emergency_number: str) -> str:
    return (
        f"Your message mentions {reason}, which can be an emergency. Please call {emergency_number} "
        "(or your local emergency number) or go to the nearest emergency department now. "
        "Do not wait for a scheduled appointment. This assistant cannot help with emergencies."
    )
