"""
Payment Case Engine — manages case state and event processing.
All state transitions are deterministic.
"""
import json
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.database import PaymentCase, Event, Transaction, RecoveryIntervention
from app.services.health_score import calculate_health_score, score_to_status

# ─────────────────────────────────────────────
# Stopping rules — hard limits per case
# ─────────────────────────────────────────────
MAX_INTERVENTIONS_PER_CASE = 3          # stop chasing after 3 attempts
MAX_ESCALATIONS_PER_CASE = 1            # only escalate to dispute once
AUTO_DISPUTE_AFTER_ATTEMPTS = 3         # auto-prepare dispute after 3 failed attempts
RECOVERY_CHANNELS = ["email", "sms", "whatsapp"]  # escalation order


def get_or_create_case(db: Session, transaction_id: int, case_type: str) -> PaymentCase:
    """Get existing case or create a new one for a transaction."""
    case = db.query(PaymentCase).filter(
        PaymentCase.transaction_id == transaction_id
    ).first()

    if not case:
        case = PaymentCase(
            transaction_id=transaction_id,
            case_type=case_type,
            health_score=100.0,
            status="monitoring",
            risk_level="low",
        )
        db.add(case)
        db.commit()
        db.refresh(case)

    return case


def add_event(db: Session, case_id: int, event_type: str, event_data: dict = None) -> Event:
    """Add an event to a case and recalculate health score."""
    event = Event(
        case_id=case_id,
        event_type=event_type,
        event_data=json.dumps(event_data or {}),
        timestamp=datetime.utcnow(),
    )
    db.add(event)
    db.commit()

    # Recalculate health score after each new event
    recalculate_case_health(db, case_id)

    db.refresh(event)
    return event


def recalculate_case_health(db: Session, case_id: int):
    """Recalculate and persist health score for a case."""
    case = db.query(PaymentCase).filter(PaymentCase.id == case_id).first()
    if not case:
        return

    events = db.query(Event).filter(Event.case_id == case_id).all()
    event_dicts = [{"event_type": e.event_type} for e in events]

    score, _ = calculate_health_score(event_dicts)
    status, risk_level = score_to_status(score)

    case.health_score = score
    case.status = status
    case.risk_level = risk_level
    case.updated_at = datetime.utcnow()

    db.commit()


def get_case_timeline(db: Session, case_id: int) -> list:
    """Return full event timeline for a case."""
    events = db.query(Event).filter(Event.case_id == case_id).order_by(Event.timestamp).all()
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "event_data": json.loads(e.event_data) if e.event_data else {},
            "timestamp": e.timestamp.isoformat(),
        }
        for e in events
    ]


def get_case_summary(db: Session, case_id: int) -> dict:
    """Return a full summary of a payment case."""
    case = db.query(PaymentCase).filter(PaymentCase.id == case_id).first()
    if not case:
        return {}

    transaction = db.query(Transaction).filter(
        Transaction.id == case.transaction_id
    ).first()

    events = db.query(Event).filter(Event.case_id == case_id).all()
    event_dicts = [{"event_type": e.event_type} for e in events]
    score, reasons = calculate_health_score(event_dicts)

    return {
        "case_id": case.id,
        "transaction_id": case.transaction_id,
        "amount": transaction.amount if transaction else None,
        "merchant": transaction.merchant if transaction else None,
        "currency": transaction.currency if transaction else "INR",
        "case_type": case.case_type,
        "health_score": score,
        "score_reasons": reasons,
        "status": case.status,
        "risk_level": case.risk_level,
        "ai_summary": case.ai_summary,
        "created_at": case.created_at.isoformat(),
        "updated_at": case.updated_at.isoformat(),
        "timeline": get_case_timeline(db, case_id),
    }


# ─────────────────────────────────────────────
# Recovery / escalation helpers
# ─────────────────────────────────────────────

def get_intervention_count(db: Session, case_id: int) -> int:
    """Return total number of recovery interventions attempted for a case."""
    return db.query(RecoveryIntervention).filter(
        RecoveryIntervention.case_id == case_id
    ).count()


def get_escalation_count(db: Session, case_id: int) -> int:
    """Return number of dispute/escalation interventions for a case."""
    return db.query(RecoveryIntervention).filter(
        RecoveryIntervention.case_id == case_id,
        RecoveryIntervention.intervention_type.in_(["dispute", "escalate"])
    ).count()


def should_stop_recovery(db: Session, case_id: int) -> dict:
    """
    Check if recovery attempts should stop for this case.
    Returns {"stop": bool, "reason": str}
    """
    case = db.query(PaymentCase).filter(PaymentCase.id == case_id).first()
    if not case:
        return {"stop": True, "reason": "Case not found"}

    if case.status == "resolved":
        return {"stop": True, "reason": "Case already resolved"}

    total = get_intervention_count(db, case_id)
    if total >= MAX_INTERVENTIONS_PER_CASE:
        return {
            "stop": True,
            "reason": f"Max intervention limit reached ({MAX_INTERVENTIONS_PER_CASE} attempts). Escalating to dispute."
        }

    escalations = get_escalation_count(db, case_id)
    if escalations >= MAX_ESCALATIONS_PER_CASE:
        return {
            "stop": True,
            "reason": f"Already escalated to dispute. No further automated recovery."
        }

    return {"stop": False, "reason": "Recovery can proceed"}


def get_next_recovery_channel(db: Session, case_id: int) -> str:
    """Return the next channel to use based on attempt number."""
    count = get_intervention_count(db, case_id)
    idx = min(count, len(RECOVERY_CHANNELS) - 1)
    return RECOVERY_CHANNELS[idx]


def log_intervention(
    db: Session,
    case_id: int,
    intervention_type: str,
    channel: str = "email",
    message_sent: str = None,
    batch_id: int = None,
    notes: str = None,
) -> RecoveryIntervention:
    """Log a recovery intervention for a case."""
    attempt_number = get_intervention_count(db, case_id) + 1
    intervention = RecoveryIntervention(
        case_id=case_id,
        batch_id=batch_id,
        intervention_type=intervention_type,
        attempt_number=attempt_number,
        channel=channel,
        message_sent=message_sent,
        outcome="pending",
        notes=notes,
    )
    db.add(intervention)
    db.commit()
    db.refresh(intervention)
    return intervention


def mark_intervention_outcome(
    db: Session,
    intervention_id: int,
    outcome: str,
    amount_recovered: float = 0.0,
) -> RecoveryIntervention:
    """Update the outcome of a recovery intervention."""
    intervention = db.query(RecoveryIntervention).filter(
        RecoveryIntervention.id == intervention_id
    ).first()
    if intervention:
        intervention.outcome = outcome
        intervention.amount_recovered = amount_recovered
        if outcome in ("recovered", "failed", "stopped", "escalated"):
            intervention.resolved_at = datetime.utcnow()
        db.commit()
        db.refresh(intervention)
    return intervention


def get_cases_at_risk(db: Session) -> list:
    """Return all cases that need recovery (not resolved, health score < 80)."""
    cases = db.query(PaymentCase).filter(
        PaymentCase.status.in_(["needs_attention", "action_required"]),
    ).all()
    return cases


def get_recovery_summary(db: Session, case_id: int) -> dict:
    """Return recovery status for a specific case."""
    interventions = db.query(RecoveryIntervention).filter(
        RecoveryIntervention.case_id == case_id
    ).order_by(RecoveryIntervention.created_at).all()

    stop_check = should_stop_recovery(db, case_id)
    total_recovered = sum(i.amount_recovered for i in interventions)

    return {
        "case_id": case_id,
        "total_interventions": len(interventions),
        "should_stop": stop_check["stop"],
        "stop_reason": stop_check["reason"],
        "next_channel": get_next_recovery_channel(db, case_id),
        "total_amount_recovered": total_recovered,
        "interventions": [
            {
                "id": i.id,
                "type": i.intervention_type,
                "attempt": i.attempt_number,
                "channel": i.channel,
                "outcome": i.outcome,
                "amount_recovered": i.amount_recovered,
                "created_at": i.created_at.isoformat(),
            }
            for i in interventions
        ],
    }
