"""Problem 9: red-flag triage, refusals and the specialty suggestion rules."""

import pytest

from clinicdesk_agent.safety import (
    is_medical_advice_request,
    match_specialty_name,
    screen_for_emergency,
    suggest_specialty,
)


@pytest.mark.parametrize("text,code", [
    ("I have chest pain going down my arm", "chest_pain"),
    ("my son can't breathe", "breathing"),
    ("sudden numbness on one side of my body", "stroke"),
    ("the cut won't stop bleeding", "bleeding"),
    ("she had a seizure this morning", "consciousness"),
    ("my throat is closing after a bee sting", "anaphylaxis"),
    ("I keep thinking about ending it, I want to kill myself", "self_harm"),
    ("my toddler swallowed bleach", "overdose"),
])
def test_red_flags(text, code):
    flag = screen_for_emergency(text)
    assert flag is not None and flag.code == code


@pytest.mark.parametrize("text", ["I have a mild cough", "rash from the sun", "book a check-up", "poison ivy rash"])
def test_no_false_alarm_on_routine_requests(text):
    assert screen_for_emergency(text) is None


@pytest.mark.parametrize("text,specialty", [
    ("itchy rash on my elbow", "Dermatology"),
    ("stomach pain and bloating after meals", "Gastroenterology"),
    ("my knee hurts when I climb stairs", "Orthopedics"),
    ("my daughter has a fever", "Pediatrics"),
    ("panic attacks and trouble sleeping, feeling anxious", "Psychiatry"),
    ("migraine with dizziness", "Neurology"),
])
def test_specialty_suggestions(text, specialty):
    suggestion = suggest_specialty(text)
    assert suggestion.specialty == specialty and suggestion.confident


def test_unclear_symptoms_default_to_family_medicine():
    suggestion = suggest_specialty("I just feel off")
    assert suggestion.specialty == "Family Medicine" and not suggestion.confident


def test_advice_requests():
    assert is_medical_advice_request("What dose of ibuprofen should I take?")
    assert is_medical_advice_request("can you prescribe something for my cough")
    assert not is_medical_advice_request("book me a family doctor tomorrow")


def test_specialty_names():
    assert match_specialty_name("I'd like to see a cardiologist") == "Cardiology"
    assert match_specialty_name("appointment with my GP") == "Family Medicine"
    assert match_specialty_name("my GPS is broken") is None
