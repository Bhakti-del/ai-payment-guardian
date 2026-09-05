"""Stopping rules are hard limits — we never spam a customer."""

from app.services.case_engine import (
    should_stop_recovery,
    get_next_recovery_channel,
    MAX_INTERVENTIONS_PER_CASE,
    MAX_ESCALATIONS_PER_CASE,
)
from app.tools.payment_tools import trigger_recovery, escalate_case


def test_channels_escalate_email_sms_whatsapp(make_case, db_session):
    case, _ = make_case()
    expected = ["email", "sms", "whatsapp"]
    for i, channel in enumerate(expected):
        assert get_next_recovery_channel(db_session, case.id) == channel
        result = trigger_recovery(db_session, case.id, f"attempt {i + 1}")
        assert result["status"] == "intervention_triggered"
        assert result["channel"] == channel
        assert result["attempt_number"] == i + 1


def test_max_interventions_stops_recovery(make_case, db_session):
    case, _ = make_case()
    for i in range(MAX_INTERVENTIONS_PER_CASE):
        assert trigger_recovery(db_session, case.id, f"attempt {i + 1}")["status"] == "intervention_triggered"

    blocked = trigger_recovery(db_session, case.id, "one too many")
    assert blocked["status"] == "stopped"
    assert "Max intervention limit" in blocked["reason"]

    check = should_stop_recovery(db_session, case.id)
    assert check["stop"] is True


def test_max_one_escalation_per_case(make_case, db_session):
    case, _ = make_case()
    first = escalate_case(db_session, case.id, "merchant unresponsive")
    assert first["status"] == "escalated"

    second = escalate_case(db_session, case.id, "ask again")
    assert second["status"] == "stopped"
    assert "Already escalated" in second["reason"]


def test_resolved_case_never_recovered(make_case, db_session):
    from app.tools.payment_tools import mark_recovered
    case, _ = make_case()
    result = mark_recovered(db_session, case.id, amount_recovered=100.0)
    assert result["status"] == "recovered"
    assert should_stop_recovery(db_session, case.id)["stop"] is True
    assert trigger_recovery(db_session, case.id, "nope")["status"] == "stopped"