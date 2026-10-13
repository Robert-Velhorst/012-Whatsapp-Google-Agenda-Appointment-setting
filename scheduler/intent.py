from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol


SCHEDULING_TERMS = (
    "meet", "meeting", "call", "appointment", "schedule", "availability", "consultation",
    "afspreken", "afspraak", "bellen", "beschikbaar", "inplannen", "overleg", "gesprek",
)
WEEKDAYS = {
    "monday": 0, "maandag": 0, "tuesday": 1, "dinsdag": 1, "wednesday": 2, "woensdag": 2,
    "thursday": 3, "donderdag": 3, "friday": 4, "vrijdag": 4, "saturday": 5, "zaterdag": 5,
    "sunday": 6, "zondag": 6,
}


@dataclass(frozen=True)
class Intent:
    is_scheduling: bool
    duration_minutes: int
    requested_start: date
    confidence: float = 0.0
    language: str = "en"
    title: str = "Appointment"


class IntentProvider(Protocol):
    name: str

    def analyse(self, text: str, today: date, default_duration: int) -> Intent: ...


class DeterministicIntentProvider:
    """Local, auditable fallback. It never sends conversation data to an AI provider."""

    name = "deterministic-v1"

    def analyse(self, text: str, today: date, default_duration: int) -> Intent:
        lower = text.lower()
        matched_terms = [term for term in SCHEDULING_TERMS if re.search(rf"\b{re.escape(term)}\b", lower)]
        is_scheduling = bool(matched_terms)
        language = "nl" if any(term in lower for term in ("afspraak", "morgen", "maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "uur", "beschikbaar")) else "en"

        duration = default_duration
        duration_match = re.search(r"\b(\d{1,3})\s*(min(?:uten|utes?)?|mins?|uur|u|hours?|hrs?)\b", lower)
        if duration_match:
            number = int(duration_match.group(1))
            unit = duration_match.group(2)
            duration = number * 60 if unit in {"uur", "u", "hour", "hours", "hr", "hrs"} else number
            if not 15 <= duration <= 480:
                duration = default_duration

        target = today
        explicit_date = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", lower)
        if explicit_date:
            day, month = int(explicit_date.group(1)), int(explicit_date.group(2))
            year = int(explicit_date.group(3)) if explicit_date.group(3) else today.year
            if year < 100:
                year += 2000
            try:
                target = date(year, month, day)
                if target < today and not explicit_date.group(3):
                    target = date(year + 1, month, day)
            except ValueError:
                target = today
        elif "tomorrow" in lower or "morgen" in lower:
            target = today + timedelta(days=1)
        else:
            for word, index in WEEKDAYS.items():
                if re.search(rf"\b{word}\b", lower):
                    offset = (index - today.weekday()) % 7
                    target = today + timedelta(days=offset or 7)
                    break

        title = "Consultation" if any(word in lower for word in ("consultation", "consult", "advies")) else "Appointment"
        if any(word in lower for word in ("call", "bellen", "phone", "telefoon")):
            title = "Call"
        evidence = min(0.95, 0.55 + 0.12 * len(matched_terms)) if is_scheduling else 0.05
        if target != today:
            evidence = min(0.98, evidence + 0.08)
        return Intent(is_scheduling, duration, target, evidence, language, title)


DEFAULT_PROVIDER = DeterministicIntentProvider()


def analyse(text: str, today: date, default_duration: int) -> Intent:
    return DEFAULT_PROVIDER.analyse(text, today, default_duration)


def confirmation_index(text: str, slot_count: int) -> int | None:
    # A question or an incidental number is not authority to create an event.
    if "?" in text:
        return None
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    ordinals = {
        "1": 0, "one": 0, "first": 0, "eerste": 0,
        "2": 1, "two": 1, "second": 1, "tweede": 1,
        "3": 2, "three": 2, "third": 2, "derde": 2,
    }
    selection = "|".join(ordinals)
    match = re.fullmatch(
        rf"(?:(?:the|de|option|optie|number|nummer|i choose|i pick|ik kies) )?"
        rf"(?P<choice>{selection})(?: one)?"
        rf"(?: please| graag| works(?: for me)?| is fine| is good| is prima| past(?: mij)?)?",
        normalized,
    )
    if match and ordinals[match['choice']] < slot_count:
        return ordinals[match['choice']]
    if slot_count == 1 and normalized in {"yes", "yes please", "ja", "akkoord", "confirm", "bevestig"}:
        return 0
    return None
