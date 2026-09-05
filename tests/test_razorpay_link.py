"""Razorpay payment-link integration: real SDK path + graceful fallback."""

from app.services import razorpay_client
from app.services.razorpay_client import create_payment_link


def test_missing_credentials_fall_back_to_simulated(monkeypatch):
    monkeypatch.setattr(razorpay_client, "get_razorpay_client", lambda: None)
    result = create_payment_link(amount=1499, merchant="TestMerchant", case_id=1)
    assert result["simulated"] is True
    assert result["short_url"].startswith("https://rzp.io/l/recovery-")
    assert "credentials" in result["reason"].lower()


class FakeRazorpayClient:
    def __init__(self):
        self.created = []

    def payment_link_create(self, payload):
        self.created.append(payload)
        return {
            "id": "plink_test_123",
            "short_url": "https://rzp.io/r/plink_test_123",
        }


def test_real_sdk_path_returns_razorpay_link(monkeypatch):
    client = FakeRazorpayClient()
    client.payment_link = type("PL", (), {"create": client.payment_link_create})()

    monkeypatch.setattr(razorpay_client, "get_razorpay_client", lambda: client)
    result = create_payment_link(amount=1499.50, merchant="TestMerchant", case_id=7, currency="INR")

    assert result["simulated"] is False
    assert result["id"] == "plink_test_123"
    assert result["short_url"] == "https://rzp.io/r/plink_test_123"

    payload = client.created[0]
    assert payload["amount"] == 149950  # INR → paise
    assert payload["currency"] == "INR"
    assert payload["notes"]["case_id"] == "7"


def test_api_error_falls_back_gracefully(monkeypatch):
    class Boom:
        def create(self, payload):
            raise Exception("rate limit reached")

    client = type("C", (), {"payment_link": type("PL", (), {"create": Boom().create})()})()
    monkeypatch.setattr(razorpay_client, "get_razorpay_client", lambda: client)

    result = create_payment_link(amount=100, case_id=3)
    assert result["simulated"] is True
    assert "rate limit" in result["reason"]