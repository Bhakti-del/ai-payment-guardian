from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

DATABASE_URL = "sqlite:///./payment_guardian.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    transactions = relationship("Transaction", back_populates="user")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    razorpay_payment_id = Column(String, unique=True, index=True)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="INR")
    merchant = Column(String, nullable=False)
    status = Column(String, default="success")  # success, failed, pending
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="transactions")
    payment_case = relationship("PaymentCase", back_populates="transaction", uselist=False)


class PaymentCase(Base):
    __tablename__ = "payment_cases"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    case_type = Column(String, nullable=False)  # delayed_order, failed_payment, delayed_refund, suspicious, recurring
    health_score = Column(Float, default=100.0)
    status = Column(String, default="monitoring")  # monitoring, needs_attention, action_required, resolved
    risk_level = Column(String, default="low")  # low, medium, high
    ai_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    transaction = relationship("Transaction", back_populates="payment_case")
    events = relationship("Event", back_populates="payment_case", order_by="Event.timestamp")
    agent_actions = relationship("AgentAction", back_populates="payment_case")
    interventions = relationship("RecoveryIntervention", back_populates="payment_case")


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("payment_cases.id"), nullable=False)
    event_type = Column(String, nullable=False)
    event_data = Column(Text, nullable=True)  # JSON string
    timestamp = Column(DateTime, default=datetime.utcnow)

    payment_case = relationship("PaymentCase", back_populates="events")


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("payment_cases.id"), nullable=False)
    action = Column(String, nullable=False)
    reason = Column(Text, nullable=True)
    status = Column(String, default="pending")  # pending, approved, rejected, executed
    approved_by_user = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    payment_case = relationship("PaymentCase", back_populates="agent_actions")


class RecoveryBatch(Base):
    __tablename__ = "recovery_batches"

    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    total_cases = Column(Integer, default=0)
    recovered_cases = Column(Integer, default=0)
    total_amount_at_risk = Column(Float, default=0.0)
    total_amount_recovered = Column(Float, default=0.0)
    status = Column(String, default="running")  # running, completed, failed

    interventions = relationship("RecoveryIntervention", back_populates="batch")


class RecoveryIntervention(Base):
    __tablename__ = "recovery_interventions"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("recovery_batches.id"), nullable=True)
    case_id = Column(Integer, ForeignKey("payment_cases.id"), nullable=False)
    intervention_type = Column(String, nullable=False)
    # Types: payment_link, support_request, dispute, escalate, hinglish_message, promise_to_pay
    attempt_number = Column(Integer, default=1)
    channel = Column(String, default="email")  # email, sms, whatsapp, voice
    message_sent = Column(Text, nullable=True)
    outcome = Column(String, default="pending")  # pending, recovered, failed, escalated, stopped
    amount_recovered = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)

    batch = relationship("RecoveryBatch", back_populates="interventions")
    payment_case = relationship("PaymentCase", back_populates="interventions")


def create_tables():
    Base.metadata.create_all(bind=engine)
