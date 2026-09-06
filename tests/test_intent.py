from datetime import date
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


def test_confirmation_index_is_bounded():
    assert confirmation_index("The second one works", 3) == 1
    assert confirmation_index("derde graag", 3) == 2
    assert confirmation_index("4", 3) is None


@pytest.mark.parametrize("reply", ["not the second one", "1 or 2", "I have 2 questions", "2 doesn't work", "niet de tweede", "maybe 1", "Can we do 2 hours?", "1?", "second is unavailable"])
def test_confirmation_requires_unambiguous_acceptance(reply):
    assert confirmation_index(reply, 3) is None
