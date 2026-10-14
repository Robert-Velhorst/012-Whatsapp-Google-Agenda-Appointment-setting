from datetime import date, time

import pytest

from scheduler.intent import analyse, confirmation_index


def test_intent_detects_dutch_tomorrow_and_duration():
    intent = analyse("Kunnen we morgen een afspraak van 30 minuten inplannen?", date(2026, 8, 8), 60)
    assert intent.is_scheduling
    assert intent.duration_minutes == 30
    assert intent.requested_start == date(2026, 8, 9)
    assert intent.language == "nl"
    assert intent.confidence >= 0.75


def test_intent_handles_hours_and_invalid_duration():
    assert analyse("schedule a call for 2 hours", date(2026, 8, 8), 30).duration_minutes == 120
    assert analyse("schedule a call for 900 minutes", date(2026, 8, 8), 30).duration_minutes == 30


@pytest.mark.parametrize(("message", "expected"), [
    ("Can we schedule a call next Friday at 3?", time(15)),
    ("Kunnen we vrijdagmiddag een afspraak plannen?", time(14)),
    ("Can we meet around 15:30?", time(15, 30)),
    ("Can we meet next Friday at 3pm?", time(15)),
    ("Could we schedule a call for 15:30 tomorrow?", time(15, 30)),
    ("Kunnen we om 10 uur bellen?", time(10)),
    ("Can we schedule a 30 minute call tomorrow?", None),
])
def test_intent_extracts_preferred_clock_time_or_day_part(message, expected):
    assert analyse(message, date(2026, 8, 8), 60).preferred_time == expected


def test_intent_reads_compact_dutch_weekday_and_day_part():
    intent = analyse("Kunnen we vrijdagmiddag een afspraak plannen?", date(2026, 8, 8), 60)

    assert intent.requested_start == date(2026, 8, 14)
    assert intent.preferred_time == time(14)


@pytest.mark.parametrize("message", [
    "Could we schedule a call next week?",
    "Kunnen we volgende week een afspraak inplannen?",
])
def test_intent_maps_next_week_to_next_monday(message):
    intent = analyse(message, date(2026, 10, 13), 30)

    assert intent.is_scheduling
    assert intent.requested_start == date(2026, 10, 19)


def test_confirmation_index_is_bounded():
    assert confirmation_index("The second one works", 3) == 1
    assert confirmation_index("derde graag", 3) == 2
    assert confirmation_index("4", 3) is None


@pytest.mark.parametrize("reply", ["not the second one", "1 or 2", "I have 2 questions", "2 doesn't work", "niet de tweede", "maybe 1", "Can we do 2 hours?", "1?", "second is unavailable"])
def test_confirmation_requires_unambiguous_acceptance(reply):
    assert confirmation_index(reply, 3) is None
