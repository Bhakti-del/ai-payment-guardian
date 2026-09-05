"""
Shared test setup.

* Puts the backend package on sys.path (so tests run from the repo root).
* Points DATABASE_URL at an isolated temp-file SQLite DB — never touches
  the real payment_guardian.db.
* Strips Razorpay credentials so tests never hit the live Payment Links API;
  the real path is tested with a mocked client instead.
"""
import os
import shutil
import sys
import tempfile
import uuid

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_BACKEND_DIR = os.path.join(_REPO_ROOT, "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

_TEST_DIR = tempfile.mkdtemp(prefix="apg-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DIR}/test.db"

# Never hit the live Razorpay API from tests.
for _env in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"):
    os.environ.pop(_env, None)

import pytest  # noqa: E402

from app.models.database import (  # noqa: E402
    Base, engine, create_tables, SessionLocal,
    User, Transaction,
)
from app.services.case_engine import get_or_create_case, add_event  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _fresh_db():
    """One isolated DB per test session."""
    Base.metadata.drop_all(bind=engine)
    create_tables()
    yield
    Base.metadata.drop_all(bind=engine)
    shutil.rmtree(_TEST_DIR, ignore_errors=True)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def make_case(db_session):
    """Return a fresh at-risk case for a test."""

    def _make(case_type="delayed_order", amount=1499.0, merchant="TestMerchant"):
        user = db_session.query(User).first()
        if not user:
            user = User(name="Test User", email="test-user@demo.com")
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
        tx = Transaction(
            user_id=user.id,
            razorpay_payment_id=f"pay_test_{uuid.uuid4().hex[:8]}",
            amount=amount,
            currency="INR",
            merchant=merchant,
        )
        db_session.add(tx)
        db_session.commit()
        db_session.refresh(tx)
        case = get_or_create_case(db_session, tx.id, case_type)
        add_event(db_session, case.id, "payment_failed", {"reason": "card_expired"})
        return case, tx

    return _make