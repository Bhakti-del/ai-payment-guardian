"""End-to-end recovery flow and outcome measurement."""

from app.tools.payment_tools import trigger_recovery, mark_recovered
from app.services.case_engine import get_recovery_summary, should_stop_recovery


def test_intervention_carries_payment_link_and_message(make_case, db_session):
    case, tx = make_case()
    result = trigger_recovery(db_session, case.id, "customer unresponsive")

    assert result["status"] == "intervention_triggered"
    assert result["case_id"] == case.id
    assert "rzp.io/l/recovery-" in result["payment_link"]
    assert result["simulated_link"] is True
    assert tx.merchant in result["message_preview"]
    assert result["payment_link"] in result["message_preview"]


def test_recover_marks_amount_and_resolves(make_case, db_session):
    case, tx = make_case()
    intervention = trigger_recovery(db_session, case.id, "initial outreach")
    assert intervention["status"] == "intervention_triggered"

    recovered = mark_recovered(db_session, case.id, amount_recovered=tx.amount)
    assert recovered["status"] == "recovered"
    assert recovered["case_id"] == case.id

    case_state = db_session.refresh(case) or case
    summary = get_recovery_summary(db_session, case.id)
    assert summary["total_amount_recovered"] == tx.amount
    assert summary["interventions"][0]["outcome"] == "recovered"
    assert summary["should_stop"] is True


def test_audit_trail_logs_every_attempt(make_case, db_session):
    case, _ = make_case()
    for i in range(3):
        trigger_recovery(db_session, case.id, f"attempt {i + 1}")

    summary = get_recovery_summary(db_session, case.id)
    assert summary["total_interventions"] == 3
    assert [i["type"] for i in summary["interventions"]] == ["payment_link"] * 3
    assert [i["attempt"] for i in summary["interventions"]] == [1, 2, 3]
    assert should_stop_recovery(db_session, case.id)["stop"] is True


def test_escalation_is_always_pending_approval(make_case, db_session):
    from app.models.database import AgentAction
    from app.tools.payment_tools import escalate_case

    case, _ = make_case()
    # Run out of interventions first so escalation is the allowed next step
    for i in range(3):
        trigger_recovery(db_session, case.id, f"attempt {i + 1}")

    result = escalate_case(db_session, case.id, "3 failures — file dispute")
    assert result["status"] == "escalated"

    action = db_session.query(AgentAction).filter(AgentAction.id == result["action_id"]).first()
    assert action is not None
    assert action.status == "pending"
    assert action.approved_by_user is False