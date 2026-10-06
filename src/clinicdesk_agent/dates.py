"""Normalise the date and time phrases patients actually type.

Everything resolves against an explicit ``today`` (in the clinic time zone),
so results are deterministic and testable. Unrecognised phrases raise
:class:`DateParseError` instead of being passed through to the database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, time, timedelta

WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}
MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9, "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
PARTS_OF_DAY = {
    "morning": (time(6, 0), time(12, 0)),
    "afternoon": (time(12, 0), time(17, 0)),
    "evening": (time(17, 0), time(21, 0)),
}

_WEEKDAY_ALT = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
# When scanning free text, skip abbreviations that are also ordinary words ("sun", "sat").
_FREE_TEXT_WEEKDAY_ALT = "|".join(
    sorted((w for w in WEEKDAYS if w not in ("sun", "sat")), key=len, reverse=True)
)

# Order matters: longer / more specific phrases first.
_DATE_PATTERNS = [
    r"\d{4}-\d{2}-\d{2}",
    r"day after tomorrow",
    r"today|tomorrow|tmrw",
    r"(?:this|next) week(?:end)?",
    r"in \d{1,2} days?",
    rf"(?:this |next |on )?(?:{_FREE_TEXT_WEEKDAY_ALT})\b",
    rf"(?:{_MONTH_ALT})\.? \d{{1,2}}(?:st|nd|rd|th)?\b",
    rf"\d{{1,2}}(?:st|nd|rd|th)? (?:of )?(?:{_MONTH_ALT})\b",
]
_DATE_FINDER = re.compile(r"\b(" + "|".join(_DATE_PATTERNS) + r")", re.IGNORECASE)


class DateParseError(ValueError):
    """The phrase could not be turned into a concrete date range."""


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date  # inclusive

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise DateParseError("date range ends before it starts")

    @classmethod
    def single(cls, day: date) -> "DateRange":
        return cls(day, day)


def _next_weekday(today: date, weekday: int, *, strictly_after: bool) -> date:
    delta = (weekday - today.weekday()) % 7
    if delta == 0 and strictly_after:
        delta = 7
    return today + timedelta(days=delta)


def _month_day(month: int, day: int, today: date) -> date:
    """Next occurrence of month/day that is not in the past."""
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError as exc:
            raise DateParseError(f"invalid day {day} for month {month}") from exc
        if candidate >= today:
            return candidate
    raise DateParseError("could not resolve month/day")  # pragma: no cover


def resolve_date_phrase(phrase: str, today: date) -> DateRange:
    """Turn a single date phrase into a concrete inclusive :class:`DateRange`."""
    text = re.sub(r"\s+", " ", phrase.strip().lower()).rstrip(".")
    if not text:
        raise DateParseError("empty date phrase")

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return DateRange.single(date.fromisoformat(text))
        except ValueError as exc:
            raise DateParseError(f"invalid ISO date {phrase!r}") from exc
    if text == "today":
        return DateRange.single(today)
    if text in ("tomorrow", "tmrw"):
        return DateRange.single(today + timedelta(days=1))
    if text == "day after tomorrow":
        return DateRange.single(today + timedelta(days=2))
    if text == "this week":
        return DateRange(today, today + timedelta(days=6 - today.weekday()))
    if text == "next week":
        monday = today + timedelta(days=7 - today.weekday())
        return DateRange(monday, monday + timedelta(days=6))
    if text in ("this weekend", "next weekend"):
        saturday = _next_weekday(today, 5, strictly_after=False)
        if text == "next weekend":
            saturday += timedelta(days=7)
        return DateRange(saturday, saturday + timedelta(days=1))

    match = re.fullmatch(r"in (\d{1,2}) days?", text)
    if match:
        return DateRange.single(today + timedelta(days=int(match.group(1))))

    match = re.fullmatch(rf"(this |next |on )?({_WEEKDAY_ALT})", text)
    if match:
        qualifier = (match.group(1) or "").strip()
        day = _next_weekday(today, WEEKDAYS[match.group(2)], strictly_after=(qualifier == "next"))
        return DateRange.single(day)

    match = re.fullmatch(rf"({_MONTH_ALT})\.? (\d{{1,2}})(?:st|nd|rd|th)?", text)
    if match:
        return DateRange.single(_month_day(MONTHS[match.group(1)], int(match.group(2)), today))
    match = re.fullmatch(rf"(\d{{1,2}})(?:st|nd|rd|th)? (?:of )?({_MONTH_ALT})", text)
    if match:
        return DateRange.single(_month_day(MONTHS[match.group(2)], int(match.group(1)), today))

    raise DateParseError(f"unrecognised date {phrase!r}; try 'tomorrow', 'Friday' or 'YYYY-MM-DD'")


def find_date_phrase(text: str) -> str | None:
    """Return the first date-like phrase inside free text, or ``None``."""
    match = _DATE_FINDER.search(text)
    return match.group(1) if match else None


def find_part_of_day(text: str) -> str | None:
    lowered = text.lower()
    for name in PARTS_OF_DAY:
        if re.search(rf"\b{name}\b", lowered):
            return name
    return None


def parse_clock_time(text: str) -> time:
    """Parse '9am', '2:30 pm', '14:00' or 'noon' into a :class:`datetime.time`."""
    value = text.strip().lower().replace(".", "")
    if value == "noon":
        return time(12, 0)
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", value)
    if not match:
        raise DateParseError(f"unrecognised time {text!r}")
    hour, minute, meridiem = int(match.group(1)), int(match.group(2) or 0), match.group(3)
    if meridiem:
        if not 1 <= hour <= 12:
            raise DateParseError(f"invalid 12-hour time {text!r}")
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise DateParseError(f"invalid time {text!r}")
    return time(hour, minute)
