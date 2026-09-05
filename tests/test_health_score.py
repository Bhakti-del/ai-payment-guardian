"""Health score is deterministic and explainable — no AI involved."""

from app.services.health_score import (
    calculate_health_score,
    score_to_label,
    score_to_status,
)


def test_healthy_case_scores_100():
    events = [
        {"event_type": "payment_success"},
        {"event_type": "order_confirmed"},
        {"event_type": "delivery_completed"},
    ]
    score, reasons = calculate_health_score(events)
    assert score == 100.0
    assert any("Delivery completed" in r for r in reasons)


def test_payment_failed_deducts_50():
    score, reasons = calculate_health_score([{"event_type": "payment_failed"}])
    assert score == 50.0
    assert any("Payment failed" in r for r in reasons)


def test_suspicious_activity_scores_low():
    score, reasons = calculate_health_score([{"event_type": "suspicious_activity"}])
    assert score == 45.0
    assert any("Suspicious activity" in r for r in reasons)


def test_score_clamped_to_bounds():
    score, _ = calculate_health_score([{"event_type": "suspicious_activity"}, {"event_type": "merchant_unresponsive"}])
    assert score >= 0.0

    score, _ = calculate_health_score([{"event_type": "refund_completed"}])  # bonus on healthy
    assert score <= 100.0


def test_status_boundaries():
    assert score_to_status(100.0)[0] == "monitoring"
    assert score_to_status(80.0)[0] == "monitoring"
    assert score_to_status(79.0)[0] == "needs_attention"
    assert score_to_status(50.0)[0] == "needs_attention"
    assert score_to_status(49.0)[0] == "action_required"
    assert score_to_status(0.0)[0] == "action_required"


def test_labels():
    assert score_to_label(90) == "Healthy"
    assert score_to_label(60) == "Needs Attention"
    assert score_to_label(30) == "Action Required"


def test_every_reason_is_explainable():
    _, reasons = calculate_health_score([{"event_type": "payment_failed"}, {"event_type": "delivery_delayed"}])
    assert len(reasons) == 2
    for reason in reasons:
        assert ("-" in reason or "+" in reason) and "pts" in reason