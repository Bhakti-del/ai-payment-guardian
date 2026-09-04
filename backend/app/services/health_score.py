"""
Health Score Calculator — fully deterministic, no AI involved.
Score is explainable: each deduction has a clear reason.
"""
import json
from typing import List, Tuple


# Event types
EVENT_PAYMENT_SUCCESS = "payment_success"
EVENT_PAYMENT_FAILED = "payment_failed"
EVENT_ORDER_CONFIRMED = "order_confirmed"
EVENT_ORDER_CANCELLED = "order_cancelled"
EVENT_DELIVERY_DELAYED = "delivery_delayed"
EVENT_DELIVERY_COMPLETED = "delivery_completed"
EVENT_REFUND_INITIATED = "refund_initiated"
EVENT_REFUND_COMPLETED = "refund_completed"
EVENT_REFUND_DELAYED = "refund_delayed"
EVENT_MERCHANT_UNRESPONSIVE = "merchant_unresponsive"
EVENT_SUSPICIOUS_ACTIVITY = "suspicious_activity"
EVENT_DISPUTE_OPENED = "dispute_opened"
EVENT_DISPUTE_RESOLVED = "dispute_resolved"
EVENT_SUPPORT_CONTACTED = "support_contacted"


SCORE_DEDUCTIONS = {
    EVENT_PAYMENT_FAILED: (50, "Payment failed"),
    EVENT_ORDER_CANCELLED: (25, "Order was cancelled"),
    EVENT_DELIVERY_DELAYED: (25, "Delivery is overdue"),
    EVENT_REFUND_DELAYED: (35, "Refund is taking longer than expected"),
    EVENT_MERCHANT_UNRESPONSIVE: (15, "Merchant is not responding"),
    EVENT_SUSPICIOUS_ACTIVITY: (55, "Suspicious activity detected"),
    EVENT_DISPUTE_OPENED: (10, "Dispute has been opened"),
}

SCORE_BONUSES = {
    EVENT_ORDER_CONFIRMED: (5, "Order confirmed by merchant"),
    EVENT_DELIVERY_COMPLETED: (10, "Delivery completed successfully"),
    EVENT_REFUND_COMPLETED: (15, "Refund received"),
    EVENT_DISPUTE_RESOLVED: (10, "Dispute resolved"),
    EVENT_SUPPORT_CONTACTED: (2, "Support has been contacted"),
}


def calculate_health_score(events: List[dict]) -> Tuple[float, List[str]]:
    """
    Takes a list of event dicts with 'event_type' keys.
    Returns (score, list_of_reasons).
    Score starts at 100 and is adjusted based on events.
    """
    score = 100.0
    reasons = []
    event_types = [e["event_type"] for e in events]

    for event_type, (deduction, reason) in SCORE_DEDUCTIONS.items():
        if event_type in event_types:
            score -= deduction
            reasons.append(f"- {reason} (-{deduction} pts)")

    for event_type, (bonus, reason) in SCORE_BONUSES.items():
        if event_type in event_types:
            score += bonus
            reasons.append(f"+ {reason} (+{bonus} pts)")

    # Clamp between 0 and 100
    score = max(0.0, min(100.0, score))

    return round(score, 1), reasons


def score_to_status(score: float) -> Tuple[str, str]:
    """Returns (status, risk_level) from score."""
    if score >= 80:
        return "monitoring", "low"
    elif score >= 50:
        return "needs_attention", "medium"
    else:
        return "action_required", "high"


def score_to_label(score: float) -> str:
    if score >= 80:
        return "Healthy"
    elif score >= 50:
        return "Needs Attention"
    else:
        return "Action Required"
