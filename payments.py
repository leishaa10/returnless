"""
ReturnLess - Payment service (Razorpay), standard library only.

Two modes, picked automatically at start-up:

  "razorpay"  RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are set. Orders are created
              through the real Razorpay Orders API and paid through Razorpay
              Checkout (works with rzp_test_ keys and with rzp_live_ keys).

  "mock"      No keys set (default). A simulated gateway stands in for Razorpay so
              the whole flow can be demonstrated offline, with no account and no KYC.
              The server-side flow is identical: create order -> checkout ->
              HMAC-SHA256 signature verification -> plan activated.

Optional environment variables:
  RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET   API keys (Dashboard -> Account & Settings -> API Keys)
  RAZORPAY_WEBHOOK_SECRET                secret set on the webhook in the Razorpay dashboard
  RAZORPAY_MODE=mock                     force the simulated gateway even if keys are set
  RETURNLESS_CURRENCY=USD|INR            currency plans are charged in (default USD)
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import urllib.error
import urllib.request

import database as db

RZ_API_BASE = "https://api.razorpay.com/v1"

KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "").strip()
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "").strip()

_forced = os.environ.get("RAZORPAY_MODE", "").strip().lower()
if _forced == "mock" or not (KEY_ID and KEY_SECRET):
    MODE = "mock"
else:
    MODE = "razorpay"

# Only used to sign simulated payments. It is not a real secret and is never used
# in "razorpay" mode, where the real Key Secret signs and verifies.
MOCK_SECRET = "returnless_mock_gateway_secret"
SIGNING_SECRET = KEY_SECRET if MODE == "razorpay" else MOCK_SECRET

# (monthly price, per-month price when billed annually) in the smallest currency
# unit (cents / paise). These match the prices shown on the Plans page. Amounts
# are decided here on the server, never taken from the browser.
PLAN_PRICES = {
    "USD": {
        "Starter SME": (9900, 7900),
        "Growth Tier": (29900, 23900),
        "Enterprise Tier": (79900, 69900),
    },
    "INR": {
        "Starter SME": (249900, 199900),
        "Growth Tier": (749900, 599900),
        "Enterprise Tier": (1999900, 1599900),
    },
}
CURRENCY = os.environ.get("RETURNLESS_CURRENCY", "USD").strip().upper()
if CURRENCY not in PLAN_PRICES:
    CURRENCY = "USD"


class PaymentError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def public_config():
    """Everything the browser needs to know. The Key Secret is never included."""
    return {
        "mode": MODE,
        "currency": CURRENCY,
        "key_id": KEY_ID if MODE == "razorpay" else None,
        "test_keys": KEY_ID.startswith("rzp_test_") if MODE == "razorpay" else True,
    }


def plan_amount(plan, cycle):
    prices = PLAN_PRICES[CURRENCY]
    if plan not in prices:
        raise PaymentError("Unknown plan")
    if cycle not in ("monthly", "annual"):
        raise PaymentError("Billing cycle must be 'monthly' or 'annual'")
    monthly, annual_per_month = prices[plan]
    return monthly if cycle == "monthly" else annual_per_month * 12


def _sign(order_id, payment_id):
    """Razorpay signature = HMAC-SHA256(order_id + '|' + payment_id, key_secret)."""
    message = f"{order_id}|{payment_id}".encode("utf-8")
    return hmac.new(SIGNING_SECRET.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _razorpay_create_order(amount, receipt, notes):
    auth = base64.b64encode(f"{KEY_ID}:{KEY_SECRET}".encode("utf-8")).decode("ascii")
    body = json.dumps({
        "amount": amount,
        "currency": CURRENCY,
        "receipt": receipt,
        "notes": notes,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{RZ_API_BASE}/orders",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Basic {auth}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("error", {}).get("description")
        except Exception:
            detail = None
        raise PaymentError(f"Razorpay rejected the order: {detail or e.reason}", 502)
    except (urllib.error.URLError, TimeoutError):
        raise PaymentError("Could not reach Razorpay. Check your internet connection.", 502)


def create_order(merchant_id, plan, cycle):
    amount = plan_amount(plan, cycle)
    receipt = "rcpt_" + secrets.token_hex(6)
    if MODE == "razorpay":
        order = _razorpay_create_order(amount, receipt, {"plan": plan, "cycle": cycle, "merchant_id": merchant_id})
        order_id = order["id"]
    else:
        order_id = "order_mock_" + secrets.token_hex(7)
    db.create_payment(merchant_id, order_id, plan, cycle, amount, CURRENCY, MODE)
    return {
        "order_id": order_id,
        "amount": amount,
        "currency": CURRENCY,
        "plan": plan,
        "cycle": cycle,
        **public_config(),
    }


def mock_authorize(order_id, outcome="success"):
    """Stands in for the customer paying inside Razorpay Checkout (mock mode only).

    Returns the same three fields Razorpay Checkout hands to the browser after a
    successful payment, so the /verify step is exactly the same as in real mode.
    """
    if MODE != "mock":
        raise PaymentError("The simulated checkout is disabled while Razorpay keys are configured.", 403)
    payment = db.get_payment_by_order(order_id)
    if not payment:
        raise PaymentError("Unknown order", 404)
    if payment["status"] == "paid":
        raise PaymentError("This order has already been paid", 409)
    if outcome == "failure":
        db.mark_payment_failed(order_id, "Payment declined by the bank (simulated)")
        raise PaymentError("The bank declined this payment (simulated). No money was charged.", 402)
    payment_id = "pay_mock_" + secrets.token_hex(7)
    return {
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": _sign(order_id, payment_id),
    }


def verify_payment(order_id, payment_id, signature):
    """Authenticate a payment and only then activate the plan."""
    if not (order_id and payment_id and signature):
        raise PaymentError("Missing payment details")
    payment = db.get_payment_by_order(order_id)
    if not payment:
        raise PaymentError("Unknown order", 404)
    expected = _sign(order_id, payment_id).encode("utf-8")
    if not hmac.compare_digest(expected, str(signature).encode("utf-8")):
        raise PaymentError("Payment signature mismatch. The payment was not verified.", 400)
    # The plan (and which company it belongs to) comes from OUR record of
    # the order, never from the browser.
    payment = db.mark_payment_paid(order_id, payment_id)
    profile = db.set_plan(payment["merchant_id"], payment["plan"])
    return payment, profile


def report_failure(order_id, reason=""):
    payment = db.get_payment_by_order(order_id)
    if not payment:
        raise PaymentError("Unknown order", 404)
    return db.mark_payment_failed(order_id, reason or "Payment failed")


def handle_webhook(raw_body, signature):
    """Razorpay -> server notification, so a closed browser tab can't lose a payment."""
    if MODE != "razorpay" or not WEBHOOK_SECRET:
        raise PaymentError("Webhook is not configured", 503)
    expected = hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(expected.encode("utf-8"), signature.encode("utf-8")):
        raise PaymentError("Invalid webhook signature", 400)

    event = json.loads(raw_body.decode("utf-8"))
    name = event.get("event", "")
    entity = event.get("payload", {}).get("payment", {}).get("entity", {})
    order_id, payment_id = entity.get("order_id"), entity.get("id")
    payment = db.get_payment_by_order(order_id) if order_id else None
    if not payment:
        return {"handled": False, "event": name}

    if name in ("payment.captured", "order.paid"):
        db.mark_payment_paid(order_id, payment_id, entity.get("method"))
        db.set_plan(payment["merchant_id"], payment["plan"])
    elif name == "payment.failed":
        db.mark_payment_failed(order_id, entity.get("error_description") or "Payment failed")
    return {"handled": True, "event": name}
