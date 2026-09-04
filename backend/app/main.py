import os
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

from app.models.database import (
    get_db, create_tables, User, Transaction,
    PaymentCase, Event, AgentAction, RecoveryBatch, RecoveryIntervention
)
from app.services.case_engine import (
    get_or_create_case, add_event, get_case_summary, get_case_timeline,
    get_cases_at_risk, get_recovery_summary, should_stop_recovery,
)
from app.services.health_score import score_to_label
from app.services.seed import seed

app = FastAPI(title="AI Payment Guardian", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize DB and seed on startup
@app.on_event("startup")
def startup():
    create_tables()
    seed()


# ─────────────────────────────────────────────
# Dashboard endpoints
# ─────────────────────────────────────────────

@app.get("/api/cases")
def list_cases(db: Session = Depends(get_db)):
    """List all payment cases with summary info, sorted by urgency."""
    cases = db.query(PaymentCase).all()
    result = []
    for case in cases:
        tx = db.query(Transaction).filter(Transaction.id == case.transaction_id).first()
        result.append({
            "case_id": case.id,
            "transaction_id": case.transaction_id,
            "amount": tx.amount if tx else None,
            "merchant": tx.merchant if tx else None,
            "currency": tx.currency if tx else "INR",
            "case_type": case.case_type,
            "health_score": case.health_score,
            "health_label": score_to_label(case.health_score),
            "status": case.status,
            "risk_level": case.risk_level,
            "updated_at": case.updated_at.isoformat(),
        })

    # Sort: action_required first → needs_attention → monitoring/resolved
    # Within each group, sort by health_score ascending (worst first)
    status_order = {"action_required": 0, "needs_attention": 1, "monitoring": 2, "resolved": 3}
    result.sort(key=lambda c: (status_order.get(c["status"], 2), c["health_score"] or 100))
    return result


@app.get("/api/cases/{case_id}")
def get_case(case_id: int, db: Session = Depends(get_db)):
    """Get full details of a payment case."""
    summary = get_case_summary(db, case_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Case not found")
    return summary


@app.get("/api/cases/{case_id}/timeline")
def case_timeline(case_id: int, db: Session = Depends(get_db)):
    """Get event timeline for a case."""
    return get_case_timeline(db, case_id)


# ─────────────────────────────────────────────
# Event simulation endpoint
# ─────────────────────────────────────────────

class SimulateEventRequest(BaseModel):
    event_type: str
    event_data: Optional[dict] = {}


@app.post("/api/cases/{case_id}/simulate")
def simulate_event(case_id: int, body: SimulateEventRequest, db: Session = Depends(get_db)):
    """Simulate a new event on a case (demo use)."""
    case = db.query(PaymentCase).filter(PaymentCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    event = add_event(db, case_id, body.event_type, body.event_data)
    updated_case = get_case_summary(db, case_id)

    return {
        "event_added": body.event_type,
        "new_health_score": updated_case["health_score"],
        "new_status": updated_case["status"],
    }


# ─────────────────────────────────────────────
# AI Agent endpoint
# ─────────────────────────────────────────────

class AgentQueryRequest(BaseModel):
    message: str
    case_id: Optional[int] = None
    transaction_id: Optional[int] = None


@app.post("/api/agent/query")
def agent_query(body: AgentQueryRequest, db: Session = Depends(get_db)):
    """Ask the AI agent a question about a payment case."""
    try:
        from app.agents.payment_agent import PaymentAgent
        agent = PaymentAgent()
        result = agent.investigate(
            db=db,
            user_message=body.message,
            case_id=body.case_id,
            transaction_id=body.transaction_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")


# ─────────────────────────────────────────────
# User approval endpoint
# ─────────────────────────────────────────────

class ApproveActionRequest(BaseModel):
    approved: bool


@app.post("/api/actions/{action_id}/approve")
def approve_action(action_id: int, body: ApproveActionRequest, db: Session = Depends(get_db)):
    """Approve or reject a pending agent action."""
    action = db.query(AgentAction).filter(AgentAction.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    if action.status != "pending":
        raise HTTPException(status_code=400, detail="Action is not pending")

    if body.approved:
        action.status = "approved"
        action.approved_by_user = True
        message = f"Action '{action.action}' approved and submitted."
    else:
        action.status = "rejected"
        message = f"Action '{action.action}' rejected."

    db.commit()
    return {"action_id": action_id, "status": action.status, "message": message}


@app.get("/api/actions/pending")
def list_pending_actions(db: Session = Depends(get_db)):
    """List all pending agent actions awaiting user approval."""
    actions = db.query(AgentAction).filter(AgentAction.status == "pending").all()
    return [
        {
            "action_id": a.id,
            "case_id": a.case_id,
            "action": a.action,
            "reason": a.reason,
            "created_at": a.created_at.isoformat(),
        }
        for a in actions
    ]


# ─────────────────────────────────────────────
# Mark Resolved endpoint
# ─────────────────────────────────────────────

@app.post("/api/cases/{case_id}/resolve")
def resolve_case(case_id: int, db: Session = Depends(get_db)):
    case = db.query(PaymentCase).filter(PaymentCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    case.status = "resolved"
    case.risk_level = "low"
    case.health_score = 100.0
    case.updated_at = datetime.utcnow()
    # Add resolved event
    from app.services.case_engine import add_event
    add_event(db, case_id, "case_resolved", {"resolved_at": datetime.utcnow().isoformat()})
    db.commit()
    return {"case_id": case_id, "status": "resolved", "health_score": 100.0}


# ─────────────────────────────────────────────
# Notifications endpoint
# ─────────────────────────────────────────────

@app.get("/api/notifications")
def get_notifications(db: Session = Depends(get_db)):
    cases = db.query(PaymentCase).filter(
        PaymentCase.status.in_(["needs_attention", "action_required"])
    ).all()
    notifications = []
    for case in cases:
        tx = db.query(Transaction).filter(Transaction.id == case.transaction_id).first()
        events = db.query(Event).filter(Event.case_id == case.id).order_by(Event.timestamp.desc()).all()
        for evt in events:
            if evt.event_type in ("delivery_delayed", "merchant_unresponsive", "refund_delayed", "suspicious_activity"):
                label_map = {
                    "delivery_delayed": f"Delivery overdue for {tx.merchant if tx else 'unknown'}",
                    "merchant_unresponsive": f"{tx.merchant if tx else 'Merchant'} is not responding",
                    "refund_delayed": f"Refund delayed for {tx.merchant if tx else 'unknown'}",
                    "suspicious_activity": f"Suspicious activity on {tx.merchant if tx else 'unknown'} payment",
                }
                notifications.append({
                    "id": evt.id,
                    "case_id": case.id,
                    "type": evt.event_type,
                    "message": label_map.get(evt.event_type, evt.event_type),
                    "amount": tx.amount if tx else None,
                    "health_score": case.health_score,
                    "risk_level": case.risk_level,
                    "timestamp": evt.timestamp.isoformat(),
                })
                break  # one notification per case
    return sorted(notifications, key=lambda x: x["timestamp"], reverse=True)


# ─────────────────────────────────────────────
# Razorpay checkout endpoint
# ─────────────────────────────────────────────

class CreateOrderRequest(BaseModel):
    amount: float
    merchant: str
    currency: str = "INR"


@app.post("/api/razorpay/create-order")
def create_razorpay_order(body: CreateOrderRequest, db: Session = Depends(get_db)):
    import random, string
    payment_id = "pay_" + "".join(random.choices(string.ascii_letters + string.digits, k=16))
    user = db.query(User).first()
    if not user:
        raise HTTPException(status_code=404, detail="No user found")
    tx = Transaction(
        user_id=user.id,
        razorpay_payment_id=payment_id,
        amount=body.amount,
        currency=body.currency,
        merchant=body.merchant,
        status="success",
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    from app.services.case_engine import get_or_create_case, add_event
    from app.services.health_score import EVENT_PAYMENT_SUCCESS, EVENT_ORDER_CONFIRMED
    case = get_or_create_case(db, tx.id, "normal")
    add_event(db, case.id, EVENT_PAYMENT_SUCCESS, {"amount": body.amount, "merchant": body.merchant})
    add_event(db, case.id, EVENT_ORDER_CONFIRMED, {"order_id": f"ORD-{tx.id:04d}"})
    return {
        "payment_id": payment_id,
        "transaction_id": tx.id,
        "case_id": case.id,
        "amount": body.amount,
        "merchant": body.merchant,
        "message": "Payment successful. Payment Guardian is now monitoring this transaction."
    }


# ─────────────────────────────────────────────
# Recovery batch endpoints (Track 03)
# ─────────────────────────────────────────────

@app.post("/api/recovery/batch")
def run_recovery_batch(db: Session = Depends(get_db)):
    """
    Run recovery across all at-risk cases using rule-based logic.
    Fast, deterministic, measurable — no LLM call per case.
    Returns batch metrics: cases processed, recovered, amount recovered.
    """
    import random as _random
    from app.models.database import RecoveryBatch as RBatch
    from app.tools.payment_tools import trigger_recovery, escalate_case

    batch = RBatch(started_at=datetime.utcnow(), status="running")
    db.add(batch)
    db.commit()
    db.refresh(batch)

    at_risk_cases = get_cases_at_risk(db)
    batch.total_cases = len(at_risk_cases)

    results = []
    total_amount_at_risk = 0.0
    total_recovered = 0.0
    recovered_count = 0

    for case in at_risk_cases:
        tx = db.query(Transaction).filter(Transaction.id == case.transaction_id).first()
        amount = tx.amount if tx else 0
        total_amount_at_risk += amount

        stop = should_stop_recovery(db, case.id)

        if stop["stop"]:
            results.append({
                "case_id": case.id,
                "status": "skipped",
                "reason": stop["reason"],
                "amount": amount,
                "merchant": tx.merchant if tx else "unknown",
            })
            continue

        # Check intervention count — escalate if maxed out
        from app.services.case_engine import get_intervention_count
        count = get_intervention_count(db, case.id)

        if count >= 2:
            # Max attempts reached — escalate to dispute
            result = escalate_case(
                db=db,
                case_id=case.id,
                reason=f"Recovery failed after {count} attempts for {tx.merchant if tx else 'merchant'}. Escalating to dispute.",
                batch_id=batch.id,
            )
            status = "escalated"
        else:
            # Trigger next recovery intervention
            result = trigger_recovery(
                db=db,
                case_id=case.id,
                reason=f"Batch recovery — attempt {count + 1} for {case.case_type.replace('_',' ')}",
                batch_id=batch.id,
            )
            status = result.get("status", "intervention_sent")

        # Simulate outcome: 25% recovery rate for demo
        recovered = _random.random() < 0.25
        if recovered and status != "escalated":
            from app.tools.payment_tools import mark_recovered
            mark_recovered(db=db, case_id=case.id, amount_recovered=amount,
                           notes="Recovered via batch agent run")
            total_recovered += amount
            recovered_count += 1
            status = "recovered"

        results.append({
            "case_id": case.id,
            "status": status,
            "amount": amount,
            "merchant": tx.merchant if tx else "unknown",
            "channel": result.get("channel", "—"),
            "attempt": result.get("attempt_number", count + 1),
        })

    batch.completed_at = datetime.utcnow()
    batch.recovered_cases = recovered_count
    batch.total_amount_at_risk = total_amount_at_risk
    batch.total_amount_recovered = total_recovered
    batch.status = "completed"
    db.commit()

    recovery_rate = round(recovered_count / len(at_risk_cases) * 100, 1) if at_risk_cases else 0

    return {
        "batch_id": batch.id,
        "status": "completed",
        "metrics": {
            "total_cases_processed": len(at_risk_cases),
            "recovered_cases": recovered_count,
            "recovery_rate_percent": recovery_rate,
            "total_amount_at_risk": total_amount_at_risk,
            "total_amount_recovered": total_recovered,
            "amount_still_at_risk": total_amount_at_risk - total_recovered,
        },
        "results": results,
    }


@app.get("/api/recovery/audit")
def get_recovery_audit(db: Session = Depends(get_db)):
    """
    Full audit trail of all recovery interventions across all cases.
    Shows what the agent did, which channel, and the outcome.
    """
    interventions = db.query(RecoveryIntervention).order_by(
        RecoveryIntervention.created_at.desc()
    ).all()

    audit = []
    for i in interventions:
        case = db.query(PaymentCase).filter(PaymentCase.id == i.case_id).first()
        tx = db.query(Transaction).filter(Transaction.id == case.transaction_id).first() if case else None
        audit.append({
            "intervention_id": i.id,
            "case_id": i.case_id,
            "batch_id": i.batch_id,
            "merchant": tx.merchant if tx else "unknown",
            "amount": tx.amount if tx else 0,
            "intervention_type": i.intervention_type,
            "attempt_number": i.attempt_number,
            "channel": i.channel,
            "outcome": i.outcome,
            "amount_recovered": i.amount_recovered,
            "message_preview": (i.message_sent[:100] + "...") if i.message_sent and len(i.message_sent) > 100 else i.message_sent,
            "created_at": i.created_at.isoformat(),
            "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
        })

    # Summary stats
    total = len(interventions)
    recovered = sum(1 for i in interventions if i.outcome == "recovered")
    total_recovered_amount = sum(i.amount_recovered for i in interventions)

    return {
        "summary": {
            "total_interventions": total,
            "recovered": recovered,
            "pending": sum(1 for i in interventions if i.outcome == "pending"),
            "escalated": sum(1 for i in interventions if i.outcome == "escalated"),
            "stopped": sum(1 for i in interventions if i.outcome == "stopped"),
            "total_amount_recovered": total_recovered_amount,
        },
        "audit_trail": audit,
    }


@app.get("/api/recovery/cases")
def get_recovery_cases(db: Session = Depends(get_db)):
    """List all cases at risk with their recovery status."""
    at_risk = get_cases_at_risk(db)
    result = []
    for case in at_risk:
        tx = db.query(Transaction).filter(Transaction.id == case.transaction_id).first()
        recovery = get_recovery_summary(db, case.id)
        result.append({
            "case_id": case.id,
            "merchant": tx.merchant if tx else "unknown",
            "amount": tx.amount if tx else 0,
            "case_type": case.case_type,
            "health_score": case.health_score,
            "status": case.status,
            "total_interventions": recovery["total_interventions"],
            "should_stop": recovery["should_stop"],
            "next_channel": recovery["next_channel"],
            "amount_recovered": recovery["total_amount_recovered"],
        })
    return result


@app.get("/api/recovery/metrics")
def get_recovery_metrics(db: Session = Depends(get_db)):
    """High-level recovery metrics for the dashboard."""
    all_cases = db.query(PaymentCase).all()
    at_risk = [c for c in all_cases if c.status in ("needs_attention", "action_required")]
    resolved = [c for c in all_cases if c.status == "resolved"]

    all_interventions = db.query(RecoveryIntervention).all()
    recovered_interventions = [i for i in all_interventions if i.outcome == "recovered"]
    total_recovered_amount = sum(i.amount_recovered for i in recovered_interventions)

    # Amount at risk
    at_risk_amount = 0
    for case in at_risk:
        tx = db.query(Transaction).filter(Transaction.id == case.transaction_id).first()
        if tx:
            at_risk_amount += tx.amount

    batches = db.query(RecoveryBatch).order_by(RecoveryBatch.started_at.desc()).limit(5).all()

    return {
        "overview": {
            "total_cases": len(all_cases),
            "cases_at_risk": len(at_risk),
            "cases_resolved": len(resolved),
            "amount_at_risk": at_risk_amount,
            "amount_recovered": total_recovered_amount,
            "total_interventions": len(all_interventions),
            "successful_recoveries": len(recovered_interventions),
            "recovery_rate_percent": round(len(recovered_interventions) / max(len(all_interventions), 1) * 100, 1),
        },
        "recent_batches": [
            {
                "batch_id": b.id,
                "started_at": b.started_at.isoformat(),
                "total_cases": b.total_cases,
                "recovered_cases": b.recovered_cases,
                "amount_recovered": b.total_amount_recovered,
                "status": b.status,
            }
            for b in batches
        ],
    }


# ─────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "AI Payment Guardian"}
