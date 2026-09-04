"""
Agent tools — these are the functions the AI agent can call.
Each tool returns clean, structured data. No raw DB objects exposed to LLM.
"""
import json
import random
from sqlalchemy.orm import Session
from app.models.database import Transaction, PaymentCase, Event, AgentAction, RecoveryIntervention
from app.services.health_score import calculate_health_score, score_to_label
from app.services.case_engine import (
    get_case_summary, get_case_timeline,
    should_stop_recovery, log_intervention, get_next_recovery_channel,
    get_recovery_summary, mark_intervention_outcome,
)


def get_transaction(db: Session, transaction_id: int) -> dict:
    """Get basic transaction details."""
    t = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not t:
        return {"error": f"Transaction {transaction_id} not found"}
    return {
        "transaction_id": t.id,
        "razorpay_payment_id": t.razorpay_payment_id,
        "amount": t.amount,
        "currency": t.currency,
        "merchant": t.merchant,
        "status": t.status,
        "created_at": t.created_at.isoformat(),
    }


def get_order_status(db: Session, case_id: int) -> dict:
    """Get order status from case events."""
    events = db.query(Event).filter(Event.case_id == case_id).all()
    event_types = [e.event_type for e in events]

    order_confirmed = "order_confirmed" in event_types
    delivery_delayed = "delivery_delayed" in event_types
    delivery_completed = "delivery_completed" in event_types
    order_cancelled = "order_cancelled" in event_types

    if delivery_completed:
        status = "delivered"
    elif order_cancelled:
        status = "cancelled"
    elif delivery_delayed:
        status = "delayed"
    elif order_confirmed:
        status = "confirmed_awaiting_delivery"
    else:
        status = "order_not_confirmed"

    delay_info = None
    for e in events:
        if e.event_type == "delivery_delayed":
            delay_info = json.loads(e.event_data) if e.event_data else {}
            break

    return {
        "order_status": status,
        "order_confirmed": order_confirmed,
        "delivery_delayed": delivery_delayed,
        "delivery_completed": delivery_completed,
        "delay_info": delay_info,
    }


def get_refund_status(db: Session, case_id: int) -> dict:
    """Get refund status from case events."""
    events = db.query(Event).filter(Event.case_id == case_id).all()
    event_types = [e.event_type for e in events]

    refund_initiated = "refund_initiated" in event_types
    refund_completed = "refund_completed" in event_types
    refund_delayed = "refund_delayed" in event_types

    if refund_completed:
        status = "completed"
    elif refund_delayed:
        status = "delayed"
    elif refund_initiated:
        status = "initiated_awaiting"
    else:
        status = "not_initiated"

    refund_info = None
    for e in events:
        if e.event_type in ("refund_initiated", "refund_delayed", "refund_completed"):
            refund_info = json.loads(e.event_data) if e.event_data else {}
            break

    return {
        "refund_status": status,
        "refund_initiated": refund_initiated,
        "refund_completed": refund_completed,
        "refund_delayed": refund_delayed,
        "refund_info": refund_info,
    }


def get_merchant_details(db: Session, transaction_id: int) -> dict:
    """Get merchant info and responsiveness from events."""
    t = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not t:
        return {"error": "Transaction not found"}

    case = db.query(PaymentCase).filter(PaymentCase.transaction_id == transaction_id).first()
    unresponsive = False
    if case:
        events = db.query(Event).filter(Event.case_id == case.id).all()
        unresponsive = any(e.event_type == "merchant_unresponsive" for e in events)

    return {
        "merchant_name": t.merchant,
        "merchant_responsive": not unresponsive,
        "unresponsive": unresponsive,
    }


def calculate_payment_health(db: Session, case_id: int) -> dict:
    """Calculate and explain payment health score."""
    events = db.query(Event).filter(Event.case_id == case_id).all()
    event_dicts = [{"event_type": e.event_type} for e in events]
    score, reasons = calculate_health_score(event_dicts)
    return {
        "health_score": score,
        "label": score_to_label(score),
        "score_breakdown": reasons,
    }


def get_delivery_status(db: Session, case_id: int) -> dict:
    """Get delivery status details."""
    return get_order_status(db, case_id)


def get_recurring_payments(db: Session, user_id: int) -> dict:
    """Stub for recurring payments — returns simulated data for demo."""
    return {
        "recurring_payments": [
            {"merchant": "Netflix", "amount": 649, "frequency": "monthly", "next_charge": "2024-02-01"},
            {"merchant": "Spotify", "amount": 119, "frequency": "monthly", "next_charge": "2024-01-28"},
        ],
        "note": "Simulated recurring payment data for demo purposes."
    }


def create_support_request(db: Session, case_id: int, reason: str) -> dict:
    """
    Create a support/dispute request — requires user approval before execution.
    Returns a pending action, does NOT execute automatically.
    """
    action = AgentAction(
        case_id=case_id,
        action="create_support_request",
        reason=reason,
        status="pending",
        approved_by_user=False,
    )
    db.add(action)
    db.commit()
    db.refresh(action)

    return {
        "action_id": action.id,
        "status": "pending_user_approval",
        "message": "Support request prepared. Awaiting your approval before submission.",
        "reason": reason,
    }


def prepare_dispute(db: Session, case_id: int, reason: str) -> dict:
    """
    Prepare a dispute request — requires user approval.
    Returns a pending action only.
    """
    action = AgentAction(
        case_id=case_id,
        action="prepare_dispute",
        reason=reason,
        status="pending",
        approved_by_user=False,
    )
    db.add(action)
    db.commit()
    db.refresh(action)

    return {
        "action_id": action.id,
        "status": "pending_user_approval",
        "message": "Dispute prepared. Awaiting your approval before submission.",
        "reason": reason,
    }


# ─────────────────────────────────────────────
# Recovery tools (Track 03)
# ─────────────────────────────────────────────

def trigger_recovery(db: Session, case_id: int, reason: str, batch_id: int = None) -> dict:
    """
    Trigger a recovery intervention for a case.
    Checks stopping rules first. Picks the next appropriate channel.
    Sends a simulated recovery message (payment link or reminder).
    """
    stop = should_stop_recovery(db, case_id)
    if stop["stop"]:
        return {
            "status": "stopped",
            "reason": stop["reason"],
            "case_id": case_id,
        }

    case = db.query(PaymentCase).filter(PaymentCase.id == case_id).first()
    if not case:
        return {"error": f"Case {case_id} not found"}

    tx = db.query(Transaction).filter(Transaction.id == case.transaction_id).first()
    channel = get_next_recovery_channel(db, case_id)

    # Simulate Razorpay payment link generation
    payment_link = f"https://rzp.io/l/recovery-{case_id}-{random.randint(1000,9999)}"

    # Craft message based on channel
    if channel == "sms" or channel == "whatsapp":
        message = (
            f"Arre yaar! Aapka ₹{tx.amount if tx else '?'} ka payment {tx.merchant if tx else 'merchant'} "
            f"ke saath stuck hai. Ek click mein resolve karein: {payment_link}"
        )
    else:
        message = (
            f"Your payment of ₹{tx.amount if tx else '?'} with {tx.merchant if tx else 'merchant'} "
            f"needs attention. Click to resolve: {payment_link}"
        )

    intervention = log_intervention(
        db=db,
        case_id=case_id,
        intervention_type="payment_link",
        channel=channel,
        message_sent=message,
        batch_id=batch_id,
        notes=reason,
    )

    return {
        "status": "intervention_triggered",
        "intervention_id": intervention.id,
        "channel": channel,
        "attempt_number": intervention.attempt_number,
        "payment_link": payment_link,
        "message_preview": message,
        "case_id": case_id,
    }


def escalate_case(db: Session, case_id: int, reason: str, batch_id: int = None) -> dict:
    """
    Escalate a case to dispute after exhausting recovery attempts.
    Enforces the MAX_ESCALATIONS_PER_CASE stopping rule.
    """
    from app.services.case_engine import get_escalation_count, MAX_ESCALATIONS_PER_CASE

    escalations = get_escalation_count(db, case_id)
    if escalations >= MAX_ESCALATIONS_PER_CASE:
        return {
            "status": "stopped",
            "reason": "Already escalated. Cannot escalate again.",
            "case_id": case_id,
        }

    case = db.query(PaymentCase).filter(PaymentCase.id == case_id).first()
    if not case:
        return {"error": f"Case {case_id} not found"}

    # Log the escalation intervention
    intervention = log_intervention(
        db=db,
        case_id=case_id,
        intervention_type="escalate",
        channel="system",
        message_sent=f"Case escalated to dispute: {reason}",
        batch_id=batch_id,
        notes=reason,
    )

    # Create a pending AgentAction for user approval
    action = AgentAction(
        case_id=case_id,
        action="escalate_to_dispute",
        reason=reason,
        status="pending",
        approved_by_user=False,
    )
    db.add(action)
    db.commit()

    return {
        "status": "escalated",
        "intervention_id": intervention.id,
        "action_id": action.id,
        "message": f"Case {case_id} escalated to dispute. Awaiting user approval.",
        "reason": reason,
    }


def log_recovery_intervention(
    db: Session,
    case_id: int,
    intervention_type: str,
    channel: str = "email",
    message: str = None,
    notes: str = None,
    batch_id: int = None,
) -> dict:
    """
    Manually log a recovery intervention (promise-to-pay, custom contact, etc.)
    """
    stop = should_stop_recovery(db, case_id)
    if stop["stop"]:
        return {"status": "stopped", "reason": stop["reason"]}

    intervention = log_intervention(
        db=db,
        case_id=case_id,
        intervention_type=intervention_type,
        channel=channel,
        message_sent=message,
        batch_id=batch_id,
        notes=notes,
    )

    return {
        "status": "logged",
        "intervention_id": intervention.id,
        "attempt_number": intervention.attempt_number,
        "channel": channel,
        "type": intervention_type,
    }


def get_recovery_status(db: Session, case_id: int) -> dict:
    """
    Get full recovery status for a case including all interventions,
    stopping rules check, and next recommended action.
    """
    summary = get_recovery_summary(db, case_id)
    case = db.query(PaymentCase).filter(PaymentCase.id == case_id).first()
    tx = db.query(Transaction).filter(Transaction.id == case.transaction_id).first() if case else None

    return {
        **summary,
        "amount_at_risk": tx.amount if tx else 0,
        "merchant": tx.merchant if tx else "unknown",
        "case_status": case.status if case else "unknown",
        "health_score": case.health_score if case else 0,
    }


def mark_recovered(db: Session, case_id: int, amount_recovered: float, notes: str = None) -> dict:
    """
    Mark a case as recovered — updates the latest pending intervention outcome
    and resolves the case.
    """
    from datetime import datetime

    # Mark the latest pending intervention as recovered
    latest = db.query(RecoveryIntervention).filter(
        RecoveryIntervention.case_id == case_id,
        RecoveryIntervention.outcome == "pending",
    ).order_by(RecoveryIntervention.created_at.desc()).first()

    if latest:
        mark_intervention_outcome(db, latest.id, "recovered", amount_recovered)

    # Resolve the case
    case = db.query(PaymentCase).filter(PaymentCase.id == case_id).first()
    if case:
        case.status = "resolved"
        case.risk_level = "low"
        case.health_score = 100.0
        case.updated_at = datetime.utcnow()
        db.commit()

    return {
        "status": "recovered",
        "case_id": case_id,
        "amount_recovered": amount_recovered,
        "notes": notes or "Case marked as recovered by agent.",
    }



TOOL_REGISTRY = {
    "get_transaction": get_transaction,
    "get_order_status": get_order_status,
    "get_refund_status": get_refund_status,
    "get_merchant_details": get_merchant_details,
    "calculate_payment_health": calculate_payment_health,
    "get_delivery_status": get_delivery_status,
    "get_recurring_payments": get_recurring_payments,
    "create_support_request": create_support_request,
    "prepare_dispute": prepare_dispute,
    "trigger_recovery": trigger_recovery,
    "escalate_case": escalate_case,
    "log_recovery_intervention": log_recovery_intervention,
    "get_recovery_status": get_recovery_status,
    "mark_recovered": mark_recovered,
}
