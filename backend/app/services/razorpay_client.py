"""
Razorpay integration — real Payment Links via the official SDK.

When RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are configured, recovery
interventions create a *real* Razorpay payment link (verified, hosted,
collect the money on a click). If credentials are missing or the API call
fails, we fall back to a clearly-labeled simulated URL so the demo never
breaks and the agent can still be demonstrated offline.
"""
import os
from dotenv import load_dotenv

load_dotenv()

SIMULATED_PREFIX = "https://rzp.io/l/recovery-"


def get_razorpay_client():
    """Return an authenticated Razorpay client or None if not configured."""
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()

    if not key_id or not key_secret or key_id.startswith("your_"):
        return None

    try:
        import razorpay
        return razorpay.Client(auth=(key_id, key_secret))
    except Exception:
        return None


def create_payment_link(
    amount: float,
    currency: str = "INR",
    merchant: str = "Merchant",
    case_id: int = None,
    description: str = None,
) -> dict:
    """
    Create a Razorpay payment link for a recovery intervention.

    Returns:
        {
            "short_url": str,
            "id": str,
            "simulated": bool,   # True when credentials missing / API failed
            "reason": str,       # only present when simulated
        }

    Amount is in major units (INR); converted to paise for the API.
    """
    amount_paise = int(round(amount * 100))

    client = get_razorpay_client()
    if client is None:
        return {
            "short_url": f"{SIMULATED_PREFIX}{case_id}-{amount_paise}",
            "id": f"simulated_{case_id}",
            "simulated": True,
            "reason": "Razorpay credentials not configured. Add RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET to create real payment links.",
        }

    payload = {
        "amount": amount_paise,
        "currency": currency,
        "description": description or f"Payment recovery — {merchant}",
        "reference_id": f"r_case_{case_id}",
        "notes": {"case_id": str(case_id), "merchant": merchant},
        "reminder_enable": True,
    }

    try:
        link = client.payment_link.create(payload)
        return {
            "short_url": link.get("short_url"),
            "id": link.get("id"),
            "amount_paise": amount_paise,
            "simulated": False,
        }
    except Exception as exc:  # network / auth / rate-limit — never break the demo
        return {
            "short_url": f"{SIMULATED_PREFIX}{case_id}-{amount_paise}",
            "id": f"simulated_{case_id}",
            "simulated": True,
            "reason": f"Razorpay API error: {exc}",
        }