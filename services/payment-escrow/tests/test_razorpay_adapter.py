"""The Razorpay adapter against a scripted Razorpay API (httpx.MockTransport); no network."""

import base64
import hashlib
import hmac
import json
from decimal import Decimal
from uuid import UUID

import httpx
import pytest

from app.payment_port.port import (
    IdempotencyMismatch,
    InvalidPaymentRequest,
    PaymentPort,
    PaymentStatus,
    TransientPaymentError,
)
from app.payment_port.razorpay_adapter import (
    RazorpayAdapter,
    from_paise,
    signature,
    to_paise,
)

KEY_ID = "rzp_test_ZeoAuction01"
KEY_SECRET = "test-key-secret"  # noqa: S105 - fixture value
WEBHOOK_SECRET = "test-webhook-secret"  # noqa: S105 - fixture value
ORDER = UUID("00000000-0000-4000-8000-000000000301")
SELLER = UUID("00000000-0000-4000-8000-000000000002")
TOTAL = Decimal("1349.00")


class FakeRazorpay:
    """Scripted responses keyed by (method, path); records every request."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], list] = {}
        self.requests: list[httpx.Request] = []

    def on(self, method: str, path: str, *responses) -> None:
        self.routes[(method, path)] = list(responses)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        queue = self.routes.get((request.method, request.url.path.removeprefix("/v1")))
        if not queue:
            return httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})
        response = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(response, Exception):
            raise response
        status, body = response
        return httpx.Response(status, json=body)

    def body(self, index: int = -1) -> dict:
        return json.loads(self.requests[index].content)


def adapter(fake: FakeRazorpay, account: str | None = "acc_TestSeller01") -> RazorpayAdapter:
    http = httpx.AsyncClient(base_url="https://api.razorpay.com/v1", auth=(KEY_ID, KEY_SECRET),
                             transport=httpx.MockTransport(fake.handler))
    return RazorpayAdapter(key_id=KEY_ID, key_secret=KEY_SECRET, webhook_secret=WEBHOOK_SECRET,
                           linked_account_for=lambda _seller: account, http=http)


def bad_request(description: str = "bad") -> tuple[int, dict]:
    return 400, {"error": {"code": "BAD_REQUEST_ERROR", "description": description}}


def test_the_adapter_satisfies_the_port_and_refuses_live_keys():
    port: PaymentPort = adapter(FakeRazorpay())
    assert port.provider == "razorpay"
    with pytest.raises(ValueError, match="test mode only"):
        RazorpayAdapter(key_id="rzp_live_123", key_secret="s", webhook_secret="w")
    with pytest.raises(ValueError):
        RazorpayAdapter(key_id=KEY_ID, key_secret="", webhook_secret="w")


def test_amounts_convert_to_and_from_paise_exactly():
    assert to_paise(Decimal("1349.00")) == 134900
    assert to_paise(Decimal("0.01")) == 1
    assert from_paise(134999) == Decimal("1349.99")
    for bad in (Decimal("0"), Decimal("1.001"), 1.5):
        with pytest.raises(InvalidPaymentRequest):
            to_paise(bad)


async def test_create_checkout_opens_a_manual_capture_order():
    fake = FakeRazorpay()
    fake.on("POST", "/orders", (200, {"id": "order_ABC", "amount": 134900, "currency": "INR",
                                      "status": "created"}))
    session = await adapter(fake).create_checkout(ORDER, TOTAL, "INR", "ZA-202610-" + "X" * 40)
    assert (session.provider, session.provider_order_id, session.key_id) == (
        "razorpay", "order_ABC", KEY_ID)
    sent = fake.body()
    assert sent["amount"] == 134900 and sent["payment_capture"] == 0
    assert len(sent["receipt"]) == 40 and sent["notes"]["order_id"] == str(ORDER)
    auth = fake.requests[0].headers["authorization"]
    assert base64.b64decode(auth.split()[1]).decode() == f"{KEY_ID}:{KEY_SECRET}"


async def test_create_checkout_refuses_a_mismatched_order():
    fake = FakeRazorpay()
    fake.on("POST", "/orders", (200, {"id": "order_ABC", "amount": 1, "currency": "INR"}))
    with pytest.raises(InvalidPaymentRequest):
        await adapter(fake).create_checkout(ORDER, TOTAL, "INR", "r")


async def test_checkout_signature_is_hmac_of_order_and_payment():
    port = adapter(FakeRazorpay())
    good = hmac.new(KEY_SECRET.encode(), b"order_ABC|pay_XYZ", hashlib.sha256).hexdigest()
    port.verify_checkout("order_ABC", "pay_XYZ", good)
    for wrong in ("0" * 64, "", signature(KEY_SECRET, "order_ABC|pay_OTHER")):
        with pytest.raises(InvalidPaymentRequest):
            port.verify_checkout("order_ABC", "pay_XYZ", wrong)


async def test_capture_success():
    fake = FakeRazorpay()
    fake.on("POST", "/payments/pay_1/capture", (200, {"id": "pay_1", "status": "captured",
                                                      "amount": 134900}))
    result = await adapter(fake).capture("pay_1", TOTAL, "INR", "order:1:capture")
    assert result.succeeded and result.provider_ref == "pay_1"
    assert fake.body() == {"amount": 134900, "currency": "INR"}


async def test_capture_of_an_already_captured_payment_is_the_original_success():
    fake = FakeRazorpay()
    fake.on("POST", "/payments/pay_1/capture", bad_request("This payment has already been "
                                                           "captured"))
    fake.on("GET", "/payments/pay_1", (200, {"id": "pay_1", "status": "captured",
                                             "amount": 134900}))
    assert (await adapter(fake).capture("pay_1", TOTAL, "INR", "k")).succeeded


async def test_capture_of_a_failed_payment_is_a_decline():
    fake = FakeRazorpay()
    fake.on("POST", "/payments/pay_1/capture", bad_request())
    fake.on("GET", "/payments/pay_1", (200, {"id": "pay_1", "status": "failed",
                                             "amount": 134900, "error_reason": "payment_failed"}))
    result = await adapter(fake).capture("pay_1", TOTAL, "INR", "k")
    assert result.status is PaymentStatus.DECLINED and result.decline_reason == "payment_failed"


async def test_capture_refused_for_another_reason_is_definitive():
    fake = FakeRazorpay()
    fake.on("POST", "/payments/pay_1/capture", bad_request("amount mismatch"))
    fake.on("GET", "/payments/pay_1", (200, {"id": "pay_1", "status": "authorized",
                                             "amount": 134900}))
    with pytest.raises(InvalidPaymentRequest, match="amount mismatch"):
        await adapter(fake).capture("pay_1", TOTAL, "INR", "k")


async def test_capture_answer_that_is_not_captured_is_refused():
    fake = FakeRazorpay()
    fake.on("POST", "/payments/pay_1/capture", (200, {"id": "pay_1", "status": "authorized",
                                                      "amount": 134900}))
    with pytest.raises(InvalidPaymentRequest):
        await adapter(fake).capture("pay_1", TOTAL, "INR", "k")


@pytest.mark.parametrize("failure", [
    (503, {"error": {"code": "SERVER_ERROR"}}),
    (429, {"error": {"code": "TOO_MANY_REQUESTS"}}),
    httpx.ConnectTimeout("timed out"),
])
async def test_outages_are_transient(failure):
    fake = FakeRazorpay()
    fake.on("POST", "/payments/pay_1/capture", failure)
    with pytest.raises(TransientPaymentError):
        await adapter(fake).capture("pay_1", TOTAL, "INR", "k")


async def test_non_json_errors_are_still_reported():
    fake = FakeRazorpay()
    fake.routes[("POST", "/orders")] = []
    port = adapter(fake)
    port.http = httpx.AsyncClient(
        base_url="https://api.razorpay.com/v1",
        transport=httpx.MockTransport(lambda _r: httpx.Response(502, text="Bad gateway")))
    with pytest.raises(TransientPaymentError, match="HTTP 502"):
        await port.create_checkout(ORDER, TOTAL, "INR", "r")


async def test_refund_creates_once_per_key():
    fake = FakeRazorpay()
    fake.on("GET", "/payments/pay_1/refunds", (200, {"items": []}))
    fake.on("POST", "/payments/pay_1/refund", (200, {"id": "rfnd_1", "amount": 125000}))
    result = await adapter(fake).refund("pay_1", Decimal("1250.00"), "INR", "order:1:refund")
    assert result.provider_ref == "rfnd_1"
    assert fake.body()["notes"] == {"idempotency_key": "order:1:refund"}


async def test_refund_retry_finds_the_earlier_refund():
    fake = FakeRazorpay()
    fake.on("GET", "/payments/pay_1/refunds", (200, {"items": [
        {"id": "rfnd_1", "amount": 125000, "notes": {"idempotency_key": "order:1:refund"}}]}))
    port = adapter(fake)
    result = await port.refund("pay_1", Decimal("1250.00"), "INR", "order:1:refund")
    assert result.provider_ref == "rfnd_1"
    assert [r.method for r in fake.requests] == ["GET"]
    with pytest.raises(IdempotencyMismatch):
        await port.refund("pay_1", Decimal("1.00"), "INR", "order:1:refund")


async def test_payout_is_a_route_transfer_to_the_linked_account():
    fake = FakeRazorpay()
    fake.on("GET", "/payments/pay_1/transfers", (200, {"items": []}))
    fake.on("POST", "/payments/pay_1/transfers", (200, {"items": [{"id": "trf_1",
                                                                   "amount": 125000}]}))
    result = await adapter(fake).payout("pay_1", SELLER, Decimal("1250.00"), "INR",
                                        "order:1:release")
    assert result.provider_ref == "trf_1"
    transfer = fake.body()["transfers"][0]
    assert (transfer["account"], transfer["amount"], transfer["on_hold"]) == (
        "acc_TestSeller01", 125000, False)


async def test_payout_retry_and_mismatch():
    fake = FakeRazorpay()
    fake.on("GET", "/payments/pay_1/transfers", (200, {"items": [
        {"id": "trf_1", "amount": 125000, "notes": {"idempotency_key": "order:1:release"}}]}))
    port = adapter(fake)
    assert (await port.payout("pay_1", SELLER, Decimal("1250.00"), "INR",
                              "order:1:release")).provider_ref == "trf_1"
    with pytest.raises(IdempotencyMismatch):
        await port.payout("pay_1", SELLER, Decimal("1.00"), "INR", "order:1:release")


async def test_payout_needs_a_linked_account_and_a_transfer():
    with pytest.raises(InvalidPaymentRequest, match="linked account"):
        await adapter(FakeRazorpay(), account=None).payout("pay_1", SELLER, Decimal("1.00"),
                                                           "INR", "k")
    fake = FakeRazorpay()
    fake.on("GET", "/payments/pay_1/transfers", (200, {"items": []}))
    fake.on("POST", "/payments/pay_1/transfers", (200, {"items": []}))
    with pytest.raises(InvalidPaymentRequest):
        await adapter(fake).payout("pay_1", SELLER, Decimal("1.00"), "INR", "k")


def webhook_body() -> bytes:
    return json.dumps({
        "entity": "event", "event": "payment.authorized", "contains": ["payment"],
        "payload": {"payment": {"entity": {"id": "pay_1", "order_id": "order_ABC",
                                           "amount": 134900, "currency": "INR",
                                           "status": "authorized"}}},
    }).encode()


def test_webhook_signature_and_parsing():
    payload = webhook_body()
    headers = {"X-Razorpay-Signature": signature(WEBHOOK_SECRET, payload),
               "X-Razorpay-Event-Id": "evt_1"}
    event = adapter(FakeRazorpay()).verify_webhook(payload, headers)
    assert (event.provider, event.event_id, event.event_type, event.provider_ref,
            event.provider_order_id, event.amount, event.currency) == (
        "razorpay", "evt_1", "payment.authorized", "pay_1", "order_ABC", TOTAL, "INR")


@pytest.mark.parametrize("headers", [{}, {"X-Razorpay-Signature": "0" * 64}])
def test_webhooks_with_a_bad_signature_are_refused(headers):
    with pytest.raises(InvalidPaymentRequest):
        adapter(FakeRazorpay()).verify_webhook(webhook_body(), headers)


def test_signed_webhooks_must_still_be_events():
    port = adapter(FakeRazorpay())
    for payload in (b"not json", b'{"entity": "event"}'):
        with pytest.raises(InvalidPaymentRequest):
            port.verify_webhook(payload, {"x-razorpay-signature": signature(WEBHOOK_SECRET,
                                                                             payload)})
