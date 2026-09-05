"""
Seed data — creates 50 varied payment cases for Track 03 (AI Revenue Recovery) demo.
Covers: failed payments, delayed refunds, abandoned checkouts, subscription failures,
        merchant unresponsive, suspicious activity, and healthy resolved cases.
"""
import random
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.database import SessionLocal, create_tables, User, Transaction
from app.services.case_engine import get_or_create_case, add_event
from app.services.health_score import (
    EVENT_PAYMENT_SUCCESS, EVENT_ORDER_CONFIRMED, EVENT_DELIVERY_DELAYED,
    EVENT_MERCHANT_UNRESPONSIVE, EVENT_REFUND_INITIATED, EVENT_REFUND_DELAYED,
    EVENT_PAYMENT_FAILED, EVENT_SUSPICIOUS_ACTIVITY, EVENT_REFUND_COMPLETED,
    EVENT_DELIVERY_COMPLETED, EVENT_DISPUTE_OPENED, EVENT_SUPPORT_CONTACTED,
)

# Isolated RNG so deterministic demo data doesn't poison the global random module
_rng = random.Random(42)


MERCHANTS = [
    "XYZ Electronics", "BookStore Online", "FashionHub", "TechGadgets India",
    "HomeDecor Plus", "SportZone", "QuickMart", "GourmetBox", "TravelEasy",
    "EduLearn Pro", "HealthFirst", "AutoSpares", "PetWorld", "GardenSupply",
    "MusicMart", "ArtSupplies Co", "ToyShop India", "BeautyBox", "FitnessGear",
    "KitchenPro", "OfficeSupplies", "LuxuryWatch", "BabyShop", "CycleWorld",
    "Unknown Merchant",
]

AMOUNTS = [299, 499, 799, 999, 1299, 1499, 1999, 2499, 2999, 3499, 4999, 5999, 7999, 9999, 14999, 19999, 24999]


def random_date(days_ago_min, days_ago_max):
    days = _rng.randint(days_ago_min, days_ago_max)
    return datetime.utcnow() - timedelta(days=days)


def seed():
    create_tables()
    db: Session = SessionLocal()

    if db.query(User).first():
        print("Database already seeded.")
        db.close()
        return

    # --- Demo user ---
    user = User(name="Bhakti", email="bhakti@demo.com")
    db.add(user)
    db.commit()
    db.refresh(user)

    case_count = 0

    # ───────────────────────────────────────────────
    # SCENARIO A: Delayed order + merchant unresponsive (10 cases)
    # These are the hardest to recover — need escalation
    # ───────────────────────────────────────────────
    for i in range(10):
        merchant = _rng.choice(MERCHANTS[:10])
        amount = _rng.choice(AMOUNTS[4:])
        tx = Transaction(
            user_id=user.id,
            razorpay_payment_id=f"pay_delayed_{i:03d}",
            amount=amount, currency="INR", merchant=merchant, status="success",
            created_at=random_date(7, 20),
        )
        db.add(tx); db.commit(); db.refresh(tx)
        case = get_or_create_case(db, tx.id, "delayed_order")
        add_event(db, case.id, EVENT_PAYMENT_SUCCESS, {"amount": amount, "merchant": merchant})
        add_event(db, case.id, EVENT_ORDER_CONFIRMED, {"order_id": f"ORD-A{i:03d}"})
        add_event(db, case.id, EVENT_DELIVERY_DELAYED, {"days_overdue": _rng.randint(2, 10)})
        if _rng.random() > 0.4:
            add_event(db, case.id, EVENT_MERCHANT_UNRESPONSIVE, {"attempts": _rng.randint(1, 3)})
        case_count += 1

    # ───────────────────────────────────────────────
    # SCENARIO B: Delayed / stuck refund (10 cases)
    # ───────────────────────────────────────────────
    for i in range(10):
        merchant = _rng.choice(MERCHANTS[5:15])
        amount = _rng.choice(AMOUNTS[3:12])
        tx = Transaction(
            user_id=user.id,
            razorpay_payment_id=f"pay_refund_{i:03d}",
            amount=amount, currency="INR", merchant=merchant, status="success",
            created_at=random_date(10, 25),
        )
        db.add(tx); db.commit(); db.refresh(tx)
        case = get_or_create_case(db, tx.id, "delayed_refund")
        add_event(db, case.id, EVENT_PAYMENT_SUCCESS, {"amount": amount})
        add_event(db, case.id, EVENT_ORDER_CONFIRMED, {"order_id": f"ORD-B{i:03d}"})
        add_event(db, case.id, EVENT_REFUND_INITIATED, {"reason": "Item not as described", "expected_days": 7})
        add_event(db, case.id, EVENT_REFUND_DELAYED, {"days_overdue": _rng.randint(3, 12)})
        case_count += 1

    # ───────────────────────────────────────────────
    # SCENARIO C: Failed subscription payment (8 cases)
    # Core Track 03 use case
    # ───────────────────────────────────────────────
    sub_merchants = ["NetflixIN", "SpotifyIN", "HotstarPremium", "ZeeTV", "SonyLIV"]
    for i in range(8):
        merchant = _rng.choice(sub_merchants)
        amount = _rng.choice([149, 199, 299, 499, 649, 999])
        tx = Transaction(
            user_id=user.id,
            razorpay_payment_id=f"pay_sub_{i:03d}",
            amount=amount, currency="INR", merchant=merchant, status="failed",
            created_at=random_date(1, 7),
        )
        db.add(tx); db.commit(); db.refresh(tx)
        case = get_or_create_case(db, tx.id, "failed_subscription")
        add_event(db, case.id, EVENT_PAYMENT_FAILED, {
            "reason": _rng.choice(["insufficient_funds", "card_expired", "bank_server_down", "otp_timeout"]),
            "merchant": merchant,
            "amount": amount,
        })
        case_count += 1

    # ───────────────────────────────────────────────
    # SCENARIO D: Suspicious / high-risk transactions (6 cases)
    # ───────────────────────────────────────────────
    for i in range(6):
        amount = _rng.choice(AMOUNTS[10:])  # high amounts
        tx = Transaction(
            user_id=user.id,
            razorpay_payment_id=f"pay_sus_{i:03d}",
            amount=amount, currency="INR", merchant="Unknown Merchant", status="success",
            created_at=random_date(1, 5),
        )
        db.add(tx); db.commit(); db.refresh(tx)
        case = get_or_create_case(db, tx.id, "suspicious")
        add_event(db, case.id, EVENT_PAYMENT_SUCCESS, {"amount": amount})
        add_event(db, case.id, EVENT_SUSPICIOUS_ACTIVITY, {
            "signals": _rng.sample(["unusual_amount", "new_merchant", "unusual_time", "multiple_attempts", "vpn_detected"], 2),
        })
        case_count += 1

    # ───────────────────────────────────────────────
    # SCENARIO E: Support contacted, awaiting resolution (6 cases)
    # ───────────────────────────────────────────────
    for i in range(6):
        merchant = _rng.choice(MERCHANTS[3:12])
        amount = _rng.choice(AMOUNTS[2:9])
        tx = Transaction(
            user_id=user.id,
            razorpay_payment_id=f"pay_sup_{i:03d}",
            amount=amount, currency="INR", merchant=merchant, status="success",
            created_at=random_date(5, 15),
        )
        db.add(tx); db.commit(); db.refresh(tx)
        case = get_or_create_case(db, tx.id, "support_pending")
        add_event(db, case.id, EVENT_PAYMENT_SUCCESS, {"amount": amount})
        add_event(db, case.id, EVENT_ORDER_CONFIRMED, {"order_id": f"ORD-E{i:03d}"})
        add_event(db, case.id, EVENT_DELIVERY_DELAYED, {"days_overdue": _rng.randint(1, 5)})
        add_event(db, case.id, EVENT_SUPPORT_CONTACTED, {"ticket_id": f"TKT-{1000+i}"})
        case_count += 1

    # ───────────────────────────────────────────────
    # SCENARIO F: Healthy / resolved payments (10 cases)
    # Baseline for recovery rate metrics
    # ───────────────────────────────────────────────
    for i in range(10):
        merchant = _rng.choice(MERCHANTS[:15])
        amount = _rng.choice(AMOUNTS[:8])
        tx = Transaction(
            user_id=user.id,
            razorpay_payment_id=f"pay_ok_{i:03d}",
            amount=amount, currency="INR", merchant=merchant, status="success",
            created_at=random_date(5, 30),
        )
        db.add(tx); db.commit(); db.refresh(tx)
        case = get_or_create_case(db, tx.id, "normal")
        add_event(db, case.id, EVENT_PAYMENT_SUCCESS, {"amount": amount})
        add_event(db, case.id, EVENT_ORDER_CONFIRMED, {"order_id": f"ORD-F{i:03d}"})
        add_event(db, case.id, EVENT_DELIVERY_COMPLETED, {"delivered_on": (datetime.utcnow() - timedelta(days=_rng.randint(1, 10))).isoformat()})
        case_count += 1

    print(f"✅ Seed data created: {case_count} cases across 6 recovery scenarios")
    print(f"   User: {user.name} ({user.email})")
    print(f"   Delayed orders: 10 | Stuck refunds: 10 | Failed subscriptions: 8")
    print(f"   Suspicious: 6 | Support pending: 6 | Healthy/resolved: 10")
    db.close()


if __name__ == "__main__":
    seed()
