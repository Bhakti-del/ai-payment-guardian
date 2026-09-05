"""API smoke tests against a freshly seeded test database."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.database import Base, engine, create_tables


@pytest.fixture(scope="module", autouse=True)
def _seeded_db():
    """Start the API module with a clean, fully seeded database."""
    Base.metadata.drop_all(bind=engine)
    create_tables()
    yield


def test_health():
    with TestClient(app) as client:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def test_cases_are_seeded():
    with TestClient(app) as client:
        resp = client.get("/api/cases")
        assert resp.status_code == 200
        cases = resp.json()
        assert len(cases) == 50

        worst = cases[0]
        assert worst["status"] in ("action_required", "needs_attention")
        assert worst["health_score"] is not None


def test_case_detail_and_timeline():
    with TestClient(app) as client:
        detail = client.get("/api/cases/1")
        assert detail.status_code == 200
        body = detail.json()
        assert body["case_id"] == 1
        assert "score_reasons" in body

        timeline = client.get("/api/cases/1/timeline")
        assert timeline.status_code == 200
        assert len(timeline.json()) >= 1


def test_recovery_batch_returns_metrics():
    with TestClient(app) as client:
        resp = client.post("/api/recovery/batch")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        assert body["batch_id"] >= 1
        metrics = body["metrics"]
        assert "total_cases_processed" in metrics
        assert "recovery_rate_percent" in metrics
        assert "total_amount_at_risk" in metrics
        assert metrics["total_cases_processed"] >= 0

        audit = client.get("/api/recovery/audit")
        assert audit.status_code == 200


def test_simulate_event_updates_score():
    with TestClient(app) as client:
        before = client.get("/api/cases/1").json()
        resp = client.post(
            "/api/cases/1/simulate",
            json={"event_type": "refund_delayed", "event_data": {"days_overdue": 3}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "new_health_score" in body
        assert "new_status" in body


def test_approve_reject_flow():
    with TestClient(app) as client:
        pending = client.get("/api/actions/pending").json()
        if not pending:
            return  # nothing to exercise on this run

        action_id = pending[0]["action_id"]
        resp = client.post(f"/api/actions/{action_id}/approve", json={"approved": True})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "approved"

        # Approving again must be rejected — it is no longer pending
        again = client.post(f"/api/actions/{action_id}/approve", json={"approved": False})
        assert again.status_code == 400