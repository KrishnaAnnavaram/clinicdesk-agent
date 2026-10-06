"""Problem 3: relative dates are normalised to concrete days before any query."""

from datetime import date, time

import pytest

from clinicdesk_agent.dates import (
    DateParseError,
    DateRange,
    find_date_phrase,
    find_part_of_day,
    parse_clock_time,
    resolve_date_phrase,
)

MONDAY = date(2026, 1, 5)


@pytest.mark.parametrize("phrase,expected", [
    ("today", date(2026, 1, 5)),
    ("Tomorrow", date(2026, 1, 6)),
    ("day after tomorrow", date(2026, 1, 7)),
    ("in 3 days", date(2026, 1, 8)),
    ("Friday", date(2026, 1, 9)),
    ("monday", date(2026, 1, 5)),
    ("next monday", date(2026, 1, 12)),
    ("on Wed", date(2026, 1, 7)),
    ("2026-01-20", date(2026, 1, 20)),
    ("Jan 20th", date(2026, 1, 20)),
    ("20 January", date(2026, 1, 20)),
    ("Jan 2", date(2027, 1, 2)),  # already past this year -> next year
])
def test_single_days(phrase, expected):
    assert resolve_date_phrase(phrase, MONDAY) == DateRange.single(expected)


def test_week_ranges():
    assert resolve_date_phrase("this week", MONDAY) == DateRange(date(2026, 1, 5), date(2026, 1, 11))
    assert resolve_date_phrase("next week", MONDAY) == DateRange(date(2026, 1, 12), date(2026, 1, 18))
    assert resolve_date_phrase("this weekend", MONDAY) == DateRange(date(2026, 1, 10), date(2026, 1, 11))


@pytest.mark.parametrize("phrase", ["", "someday", "2026-02-30", "Feb 30", "13/45"])
def test_invalid_phrases_raise(phrase):
    with pytest.raises(DateParseError):
        resolve_date_phrase(phrase, MONDAY)


def test_find_date_phrase_in_free_text():
    assert find_date_phrase("any cardiology slots next week please") == "next week"
    assert find_date_phrase("can I come in the day after tomorrow?") == "day after tomorrow"
    assert find_date_phrase("I got a rash from the sun") is None  # 'sun' is not Sunday in free text
    assert find_date_phrase("nothing here") is None


def test_part_of_day_and_clock_time():
    assert find_part_of_day("tomorrow afternoon if possible") == "afternoon"
    assert parse_clock_time("2:30 pm") == time(14, 30)
    assert parse_clock_time("12am") == time(0, 0)
    assert parse_clock_time("noon") == time(12, 0)
    assert parse_clock_time("14:05") == time(14, 5)
    with pytest.raises(DateParseError):
        parse_clock_time("25:00")
