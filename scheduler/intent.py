from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, time, timedelta
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
    preferred_time: time | None = None


class IntentProvider(Protocol):
    name: str

    def analyse(self, text: str, today: date, default_duration: int) -> Intent: ...


class DeterministicIntentProvider:
    """Local, auditable fallback. It never sends conversation data to an AI provider."""

    name = "deterministic-v1"

    def analyse(self, text: str, today: date, default_duration: int) -> Intent:
        lower = text.lower()
        matched_terms = [term for term in SCHEDULING_TERMS if re.search(rf"\b{re.escape(term)}\b", lower)]
        non_new_booking_request = re.search(
            r"\b(?:don't|do not|dont)\s+(?:(?:want|need)\s+to\s+)?(?:schedule|book|arrange|meet)\b"
            r"|\b(?:don't|do not|dont)\s+want\s+(?:a\s+)?(?:meeting|call|appointment)\b"
            r"|\b(?:wil|willen)\s+geen\s+(?:afspraak|meeting|call|overleg)\b"
            r"|\bgeen\s+(?:afspraak|meeting|call|overleg)\s+(?:maken|plannen|inplannen)\b"
            r"|\b(?:cancel|cancell?ed|cancell?ing|cancellation|reschedule|rescheduled|rescheduling|"
            r"postpone|postponed|postponing|move|moved|moving|change|changed)\b"
            r"|\b(?:annuleer|annuleren|annulering|verzet|verzetten|verplaatsen|verschuif|wijzig|wijzigen|verander|veranderen)\b",
            lower,
        )
        past_or_existing_event = re.search(
            r"\b(?:i|we|they)\s+(?:already\s+)?(?:had|held|attended)\s+(?:(?:a|an|the|our|my)\s+)?(?:meeting|call|appointment)\b"
            r"|\b(?:i|we|they)\s+(?:already\s+)?have\s+(?:(?:a|an|the|our|my)\s+)(?:meeting|call|appointment)\b",
            lower,
        )
        clear_request = re.search(
            r"\b(?:can|could|would)\s+(?:we|i|you)\b"
            r"|\b(?:want|need|would like)\s+to\s+(?:schedule|book|arrange|meet|set up)\b"
            r"|\b(?:schedule|book|arrange|set up|inplannen|afspreken|plannen)\b"
            r"|\b(?:available|free)\b",
            lower,
        )
        is_scheduling = bool(matched_terms) and non_new_booking_request is None and not (
            past_or_existing_event is not None and clear_request is None
        )
        dutch_markers = (
            "afspraak", "morgen", "maandag", "dinsdag", "woensdag", "donderdag", "vrijdag",
            "uur", "beschikbaar", "volgende week", "komende week",
        )
        language = "nl" if any(term in lower for term in dutch_markers) else "en"

        duration = default_duration
        duration_pattern = r"\b(\d{1,3})\s*(min(?:uten|utes?)?|mins?|uur|u|hours?|hrs?)\b"
        duration_match = next((match for match in re.finditer(duration_pattern, lower) if not re.search(
            r"\b(?:at|om|around|about|rond)\s*$", lower[:match.start(1)],
        )), None)
        if duration_match:
            number = int(duration_match.group(1))
            unit = duration_match.group(2)
            duration = number * 60 if unit in {"uur", "u", "hour", "hours", "hr", "hrs"} else number
            if not 15 <= duration <= 480:
                duration = default_duration

        preferred_time = self._preferred_time(lower)

        target = today
        explicit_date = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", lower)
        explicit_weekday = None
        for word, index in WEEKDAYS.items():
            compact_dutch_daypart = rf"\b{word}(?:ochtend|morgen|middag|avond)\b" if word.endswith("dag") else r"(?!)"
            if re.search(rf"\b{word}\b|{compact_dutch_daypart}", lower):
                explicit_weekday = index
                break
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
        elif re.search(r"\b(?:next week|following week|volgende week|komende week)\b", lower):
            # A week-level request anchors Monday, but retains any named weekday.
            days_until_monday = 7 - today.weekday()
            target = today + timedelta(days=days_until_monday + (explicit_weekday or 0))
        elif re.search(r"\bovermorgen(?:ochtend|middag|avond)?\b|\bday after tomorrow\b", lower):
            target = today + timedelta(days=2)
        elif re.search(r"\btomorrow\b|\bmorgen(?:ochtend|middag|avond)?\b", lower):
            target = today + timedelta(days=1)
        elif explicit_weekday is not None:
            offset = (explicit_weekday - today.weekday()) % 7
            target = today + timedelta(days=offset or 7)
        else:
            target = today

        title = "Consultation" if any(word in lower for word in ("consultation", "consult", "advies")) else "Appointment"
        if any(word in lower for word in ("call", "bellen", "phone", "telefoon")):
            title = "Call"
        evidence = min(0.95, 0.55 + 0.12 * len(matched_terms)) if is_scheduling else 0.05
        if target != today:
            evidence = min(0.98, evidence + 0.08)
        return Intent(is_scheduling, duration, target, evidence, language, title, preferred_time)

    @staticmethod
    def _preferred_time(text: str) -> time | None:
        """Read a scheduling time or day-part without treating durations as clock times."""
        matches = re.finditer(
            r"\b(?:(?:at|around|about|om|rond)\s*)?(\d{1,2})(?::([0-5]\d))?\s*(am|pm|uur|u|h)?\b",
            text,
        )
        match = next((candidate for candidate in matches if (
            not (
                candidate.group(3) in {"uur", "u", "h"}
                and re.search(r"\b(?:for|van|lasting|duration of|duur van)\s*$", text[:candidate.start(1)])
            )
            and (
                re.search(r"\b(?:at|around|about|om|rond)\s*$", text[:candidate.start(1)])
                or ":" in candidate.group(0)
                or candidate.group(3)
            )
        )), None)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2) or 0)
            suffix = match.group(3)
            if suffix in {"am", "pm"}:
                if not 1 <= hour <= 12:
                    return None
                hour = (hour % 12) + (12 if suffix == "pm" else 0)
            elif 1 <= hour <= 11 and not re.search(r"(?:morning|ochtend|morgens)\b", text) and (
                re.search(r"(?:afternoon|middag|namiddag|evening|avond|vanavond)", text)
                or (hour <= 7 and re.search(r"\b(?:at|around|about|om|rond)\s*$", text[:match.start(1)]))
            ):
                # Bare office-hour requests like "Friday at 3" conventionally mean 3 pm.
                hour += 12
            if 0 <= hour <= 23:
                return time(hour, minute)

        if re.search(r"(?:morning|ochtend|morgens)\b", text):
            return time(10)
        if re.search(r"(?:afternoon|middag|namiddag)\b", text):
            return time(14)
        if re.search(r"(?:evening|avond|vanavond)\b", text):
            return time(18)
        return None


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
