from __future__ import annotations

REQUEST_STATES = {
    "detected",
    "needs_clarification",
    "proposal_pending",
    "awaiting_confirmation",
    "slot_confirmed",
    "booking_pending",
    "booked",
    "cancelled",
    "failed",
}

REQUEST_TRANSITIONS = {
    "detected": {"needs_clarification", "proposal_pending", "failed", "cancelled"},
    "needs_clarification": {"proposal_pending", "cancelled", "failed"},
    "proposal_pending": {"awaiting_confirmation", "cancelled", "failed"},
    "awaiting_confirmation": {"slot_confirmed", "proposal_pending", "cancelled", "failed"},
    "slot_confirmed": {"booking_pending", "cancelled", "failed"},
    "booking_pending": {"booked", "cancelled", "failed"},
    "booked": {"cancelled", "failed"},
    "failed": {"proposal_pending", "booking_pending", "cancelled"},
    "cancelled": set(),
}


def transition_allowed(current: str, target: str) -> bool:
    return current == target or target in REQUEST_TRANSITIONS.get(current, set())
