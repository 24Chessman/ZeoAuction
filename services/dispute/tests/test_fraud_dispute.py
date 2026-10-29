"""Tests for fraud-triggered dispute creation (#56, Plan 6)."""

from uuid import uuid4
import pytest

from app.adapters.dispute_repo import InMemoryDisputeRepository
from app.adapters.fraud_consumer import FraudAlertConsumer
from app.adapters.payment_client import InMemoryPaymentClient, OrderInfo
from app.domain.dispute import DisputeState, EvidenceKind, OpenedBy
from app.service import DisputeService
from tests.support import BUYER, NOW, SELLER
from zeo_common.audit import InMemoryAuditWriter


@pytest.fixture
def consumer_setup():
    repo = InMemoryDisputeRepository()
    payment = InMemoryPaymentClient()
    audit = InMemoryAuditWriter()
    service = DisputeService(repo, payment, audit, clock=lambda: NOW)
    consumer = FraudAlertConsumer(service)
    return consumer, repo, payment


@pytest.mark.asyncio
async def test_fraud_alert_opens_dispute_with_bid_trace(consumer_setup):
    consumer, repo, payment = consumer_setup
    order_id = uuid4()
    alert_id = uuid4()
    ring_id = uuid4()

    payment.orders[order_id] = OrderInfo(
        order_id=order_id,
        auction_id=uuid4(),
        buyer_id=BUYER,
        seller_id=SELLER,
        state="IN_ESCROW",
    )

    alert_payload = {
        "alert_id": str(alert_id),
        "auction_id": str(payment.orders[order_id].auction_id),
        "ring_id": str(ring_id),
        "score": 0.88,
        "signals": {
            "bidVelocity": 0.75,
            "selfBidRatio": 0.90,
            "fingerprintOverlap": 2,
        },
        "suspect_bidder_ids": [str(uuid4()), str(uuid4())],
        "raised_at": NOW.isoformat(),
        "auction_closes_at": NOW.isoformat(),
    }

    dispute = await consumer.handle_alert(alert_payload, order_id=order_id)
    assert dispute.state == DisputeState.OPEN
    assert dispute.opened_by == OpenedBy.FRAUD_SERVICE
    assert dispute.fraud_alert_id == alert_id
    assert dispute.opened_by_user_id is None

    # Escrow must be frozen
    assert order_id in payment.frozen

    # Evidence must have bid trace
    evidences = await repo.get_evidence(dispute.id)
    assert len(evidences) == 1
    assert evidences[0].kind == EvidenceKind.BID_TRACE
    assert evidences[0].bid_trace["score"] == 0.88
    assert evidences[0].bid_trace["ring_id"] == str(ring_id)
    assert evidences[0].bid_trace["signals"]["selfBidRatio"] == 0.90
