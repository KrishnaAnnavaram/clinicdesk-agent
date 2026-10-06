"""Rule-based safety screening and specialty suggestion.

These rules run in code *before* any language model sees the message:

* :func:`screen_for_emergency` catches red-flag symptoms and short-circuits the
  conversation with an "call emergency services" message.
* :func:`is_medical_advice_request` catches requests for a diagnosis, a
  prescription or a dose, which the assistant refuses.
* :func:`suggest_specialty` maps described symptoms to a bookable specialty with
  transparent keyword matches. It is a routing aid, not a diagnosis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SPECIALTIES = (
    "Cardiology", "Dermatology", "Family Medicine", "Gastroenterology", "General Surgery",
    "Gynecology", "Neurology", "Orthopedics", "Pediatrics", "Psychiatry",
)
DEFAULT_SPECIALTY = "Family Medicine"


@dataclass(frozen=True)
class RedFlag:
    code: str
    reason: str
    pattern: re.Pattern[str]


def _rx(*alternatives: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(alternatives) + r")", re.IGNORECASE)


RED_FLAGS: tuple[RedFlag, ...] = (
    RedFlag("chest_pain", "chest pain or pressure",
            _rx(r"chest (?:pain|pressure|tightness)", r"pain in (?:my|the) chest", r"heart attack",
                r"crushing (?:pain|feeling)")),
    RedFlag("breathing", "severe difficulty breathing",
            _rx(r"can'?t breathe", r"cannot breathe", r"unable to breathe", r"struggling to breathe",
                r"(?:severe |extreme )?shortness of breath", r"gasping", r"choking", r"lips (?:are |turning )?blue")),
    RedFlag("stroke", "possible stroke signs",
            _rx(r"face (?:is )?droop", r"drooping face", r"slurred speech", r"can'?t speak", r"stroke",
                r"sudden(?:ly)? (?:numb|weak)", r"one side of (?:my|the) body")),
    RedFlag("bleeding", "heavy bleeding",
            _rx(r"won'?t stop bleeding", r"heavy bleeding", r"bleeding (?:heavily|a lot|profusely)",
                r"coughing (?:up )?blood", r"vomiting blood")),
    RedFlag("consciousness", "loss of consciousness or seizure",
            _rx(r"passed out", r"fainted", r"unconscious", r"unresponsive", r"seizure", r"convulsion")),
    RedFlag("anaphylaxis", "possible severe allergic reaction",
            _rx(r"anaphyla", r"throat (?:is )?(?:closing|swelling|swollen)", r"swollen (?:tongue|throat)")),
    RedFlag("self_harm", "thoughts of suicide or self-harm",
            _rx(r"suicid", r"kill myself", r"end my life", r"self[- ]harm", r"hurt myself",
                r"don'?t want to (?:live|be alive)")),
    RedFlag("overdose", "possible overdose or poisoning",
            _rx(r"overdos", r"took too many (?:pills|tablets)", r"swallowed (?:bleach|poison|detergent)",
                r"been poisoned")),
    RedFlag("head_injury", "serious head injury",
            _rx(r"hit (?:my|his|her|their) head .*(?:vomit|confus|pass)", r"worst headache of my life",
                r"thunderclap headache")),
)

_ADVICE_PATTERNS = _rx(
    r"(?:what|which) (?:medicine|medication|drug|pill|antibiotic)s? should i",
    r"prescribe", r"prescription for", r"(?:what|which) dos(?:e|age)", r"how (?:much|many) (?:mg|milligrams|pills)",
    r"diagnose me", r"what (?:disease|illness|condition) do i have", r"do i have (?:cancer|diabetes|covid)",
    r"should i (?:stop|start|increase|double) (?:taking )?my",
)

# keyword -> specialty. Matching is on whole words / stems.
_SPECIALTY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Cardiology": ("palpitation", "heart racing", "irregular heartbeat", "high blood pressure", "hypertension",
                   "ankle swelling", "cholesterol"),
    "Dermatology": ("rash", "itch", "acne", "eczema", "mole", "skin", "hives", "psoriasis", "hair loss"),
    "Gastroenterology": ("stomach", "abdominal", "belly", "nausea", "diarrhea", "diarrhoea", "constipation",
                         "heartburn", "reflux", "bloating", "indigestion"),
    "Neurology": ("headache", "migraine", "dizz", "numbness", "tingling", "memory", "tremor", "vertigo"),
    "Orthopedics": ("knee", "back pain", "joint", "sprain", "fracture", "shoulder", "ankle", "hip pain",
                    "neck pain", "wrist"),
    "Gynecology": ("period", "menstrua", "pelvic", "pregnan", "vaginal", "menopause"),
    "Pediatrics": ("my child", "my son", "my daughter", "my baby", "toddler", "infant", "my kid"),
    "Psychiatry": ("anxiety", "anxious", "depress", "panic", "can't sleep", "insomnia", "mood", "stress"),
    "General Surgery": ("hernia", "lump", "gallbladder", "appendix", "wound", "cyst"),
    "Family Medicine": ("fever", "cold", "cough", "flu", "sore throat", "fatigue", "tired", "check-up",
                        "checkup", "vaccin", "runny nose"),
}


@dataclass(frozen=True)
class TriageSuggestion:
    specialty: str
    matched_keywords: tuple[str, ...]
    confident: bool
    alternatives: tuple[str, ...] = field(default_factory=tuple)


def screen_for_emergency(text: str) -> RedFlag | None:
    for flag in RED_FLAGS:
        if flag.pattern.search(text):
            return flag
    return None


def is_medical_advice_request(text: str) -> bool:
    return bool(_ADVICE_PATTERNS.search(text))


def match_specialty_name(text: str) -> str | None:
    """Find a specialty the patient names directly, e.g. 'cardiologist', 'a GP' or 'skin doctor'."""
    lowered = text.lower()
    for pattern, specialty in _SPECIALTY_ALIASES:
        if pattern.search(lowered):
            return specialty
    return None


# Regex prefixes that name a specialty directly ("cardiologist", "a GP", "skin doctor").
_SPECIALTY_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"\b{p}"), s) for p, s in (
        (r"cardio", "Cardiology"), (r"heart doctor", "Cardiology"),
        (r"dermatolog", "Dermatology"), (r"skin doctor", "Dermatology"),
        (r"family (?:medicine|doctor)", "Family Medicine"), (r"gp\b", "Family Medicine"),
        (r"general practi", "Family Medicine"), (r"gastro", "Gastroenterology"),
        (r"(?:general )?surg", "General Surgery"), (r"gyn", "Gynecology"), (r"neurolog", "Neurology"),
        (r"orthop", "Orthopedics"), (r"p(?:a)?ediatric", "Pediatrics"), (r"psychiatr", "Psychiatry"),
    )
)


def suggest_specialty(symptoms: str) -> TriageSuggestion:
    lowered = symptoms.lower()
    scores: dict[str, list[str]] = {}
    for specialty, keywords in _SPECIALTY_KEYWORDS.items():
        hits = [k for k in keywords if re.search(rf"\b{re.escape(k)}", lowered)]
        if hits:
            scores[specialty] = hits
    if not scores:
        return TriageSuggestion(DEFAULT_SPECIALTY, (), confident=False)
    # Pediatrics wins whenever a child is the patient; otherwise most keyword hits wins.
    if "Pediatrics" in scores:
        best = "Pediatrics"
    else:
        best = max(scores, key=lambda s: (len(scores[s]), s != DEFAULT_SPECIALTY))
    others = tuple(s for s in sorted(scores, key=lambda s: -len(scores[s])) if s != best)
    return TriageSuggestion(best, tuple(scores[best]), confident=True, alternatives=others)
