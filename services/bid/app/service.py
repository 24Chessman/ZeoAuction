"""The bid hot path, SDD 5.1.1 (#19, #20, #29, #30, #31).

idempotency guard -> CT-1 state -> leader + CT-3 increment -> funds -> validation (all four
rules, before any state change) -> ``server_seq`` + compare-and-set -> publish to
``bid.events`` (broker-acknowledged) -> queue for the flusher -> 202.

If the publish fails, our compare-and-set is rolled back (when nobody has outbid us since)
and the client gets 503, so an acknowledged bid is always on Kafka.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid4

from prometheus_client import CollectorRegistry, Counter, Histogram

from app.adapters.auction_client import AuctionNotFound, AuctionSnapshot, AuctionStateUnavailable
from app.adapters.bid_repo import BidRepository, StoredBid
from app.adapters.funds import FundsPort
from app.adapters.kafka_producer import BidEventPublisher, build_bid_accepted, iso_utc
from app.adapters.pricing_client import PricingClient, tier_increment
from app.domain.conflict import ConflictResolver, ContentionExceeded, PriceStore, Threshold
from app.domain.idempotency import IdempotencyConflict, IdempotencyGuard, StoredOutcome
from app.domain.model import Leader
from app.domain.sequencing import SequenceAllocator
from app.domain.validation import BidFacts, validate_bid
from app.errors import BidRejected, state_unavailable
from zeo_common import ApiError, format_money
from zeo_common.auth import Principal

logger = logging.getLogger(__name__)


class AuctionStateSource(Protocol):
    async def get_state(self, auction_id: UUID) -> AuctionSnapshot: ...


class PriceBuffer(PriceStore, Protocol):
    async def next_seq(self, auction_id: UUID) -> int: ...

    async def rollback(self, auction_id: UUID, ours: Leader, previous: Leader | None) -> bool: ...

    async def enqueue_for_flush(self, event: dict[str, Any]) -> None: ...


@dataclass(frozen=True)
class PlaceBidResult:
    status_code: int
    body: dict[str, Any]
    replay: bool = False


class BidMetrics:
    """SDD Table 9.2 metrics for the hot path. ``bid_ack_latency_seconds`` gives Plan 4's
    latency baseline its first data."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self.ack_latency = Histogram(
            "bid_ack_latency_seconds",
            "Time from request to 202 acknowledgement of an accepted bid.",
            buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.5, 1.0, 2.5),
            registry=registry,
        )
        self.accepted = Counter("bids_accepted", "Bids accepted.", registry=registry)
        self.rejected = Counter(
            "bids_rejected", "Bids rejected, by taxonomy code.", ["code"], registry=registry
        )
        self.replays = Counter(
            "bid_idempotent_replays", "Retries answered from the idempotency store.",
            registry=registry,
        )
        self.cas_retries = Counter(
            "bid_cas_retries", "Compare-and-set rounds lost to a concurrent bid.",
            registry=registry,
        )


def error_body(rejected: BidRejected) -> dict[str, Any]:
    return {"code": rejected.code, "message": rejected.message, "details": rejected.details}


def accepted_body(
    bid_id: UUID, auction_id: UUID, server_seq: int, amount: Decimal, min_next_bid: Decimal,
    accepted_at: datetime,
) -> dict[str, Any]:
    return {
        "bid_id": str(bid_id),
        "auction_id": str(auction_id),
        "server_seq": server_seq,
        "current_price": format_money(amount),
        "min_next_bid": format_money(min_next_bid),
        "accepted_at": iso_utc(accepted_at),
    }


class BidService:
    def __init__(
        self,
        *,
        auctions: AuctionStateSource,
        pricing: PricingClient,
        funds: FundsPort,
        prices: PriceBuffer,
        publisher: BidEventPublisher,
        idempotency: IdempotencyGuard,
        bids: BidRepository,
        metrics: BidMetrics,
        max_resolution_attempts: int = 5,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.auctions = auctions
        self.pricing = pricing
        self.funds = funds
        self.prices = prices
        self.publisher = publisher
        self.idempotency = idempotency
        self.bids = bids
        self.metrics = metrics
        self.clock = clock
        self.resolver = ConflictResolver(
            prices, SequenceAllocator(prices), max_attempts=max_resolution_attempts, clock=clock
        )

    async def place_bid(
        self,
        principal: Principal,
        auction_id: UUID,
        amount: Decimal,
        idempotency_key: str,
        device_fingerprint: str | None,
    ) -> PlaceBidResult:
        bidder = str(principal.user_id)
        try:
            stored = await self.idempotency.claim(idempotency_key, bidder)
        except IdempotencyConflict as exc:
            raise ApiError("CONFLICT", exc.reason, 409) from exc
        if stored is not None:
            return self._replay(stored)

        try:
            persisted = await self.bids.get_by_idempotency_key(idempotency_key)
            if persisted is not None:
                result = self._from_persisted(persisted, principal)
            else:
                result = await self._place(
                    principal, auction_id, amount, idempotency_key, device_fingerprint
                )
        except BidRejected as rejected:
            self.metrics.rejected.labels(code=rejected.code).inc()
            await self.idempotency.complete(
                idempotency_key, bidder, rejected.status_code, error_body(rejected)
            )
            raise rejected.to_api_error() from None
        except BaseException:
            await self.idempotency.release(idempotency_key)
            raise
        await self.idempotency.complete(idempotency_key, bidder, result.status_code, result.body)
        return result

    def _replay(self, stored: StoredOutcome) -> PlaceBidResult:
        self.metrics.replays.inc()
        status = 200 if stored.status_code == 202 else stored.status_code
        return PlaceBidResult(status, stored.body, replay=True)

    def _from_persisted(self, persisted: StoredBid, principal: Principal) -> PlaceBidResult:
        """Redis forgot the key (expired or lost) but the bid is in PostgreSQL."""
        if persisted.bidder_id != principal.user_id:
            raise ApiError("CONFLICT", "Idempotency-Key was already used by another request", 409)
        min_next = persisted.amount + tier_increment(persisted.amount)
        body = accepted_body(persisted.bid_id, persisted.auction_id, persisted.server_seq,
                             persisted.amount, min_next, persisted.accepted_at)
        self.metrics.replays.inc()
        return PlaceBidResult(200, body, replay=True)

    async def _threshold(self, snapshot: AuctionSnapshot, leader: Leader | None) -> Threshold:
        if leader is None:
            return Threshold(snapshot.starting_price)
        quote = await self.pricing.quote(snapshot.auction_id, leader.amount)
        return Threshold(quote.min_next_bid, quote.stale)

    async def _place(
        self,
        principal: Principal,
        auction_id: UUID,
        amount: Decimal,
        idempotency_key: str,
        device_fingerprint: str | None,
    ) -> PlaceBidResult:
        try:
            snapshot = await self.auctions.get_state(auction_id)
        except AuctionNotFound as exc:
            raise ApiError("NOT_FOUND", f"Auction {auction_id} does not exist", 404) from exc
        except AuctionStateUnavailable as exc:
            raise state_unavailable() from exc

        leader = await self.prices.leader(auction_id)
        threshold = await self._threshold(snapshot, leader)
        validate_bid(
            BidFacts(
                bidder_id=principal.user_id,
                bidder_suspended=principal.suspended,
                seller_id=snapshot.seller_id,
                auction_state=snapshot.state,
                bid_permitted=snapshot.bid_permitted,
                amount=amount,
                min_next_bid=threshold.min_next_bid,
                available_funds=await self.funds.available(principal.user_id),
            )
        )

        bid_id = uuid4()
        try:
            resolution = await self.resolver.resolve(
                auction_id=auction_id,
                bid_id=bid_id,
                bidder_id=principal.user_id,
                amount=amount,
                closes_at=snapshot.closes_at,
                threshold_for=lambda current: self._threshold(snapshot, current),
                leader=leader,
                threshold=threshold,
            )
        except ContentionExceeded as exc:
            raise ApiError(
                "CONFLICT", "The auction is too contended right now; retry", 409
            ) from exc
        if resolution.attempts > 1:
            self.metrics.cas_retries.inc(resolution.attempts - 1)

        accepted_at = self.clock()
        event = build_bid_accepted(
            event_id=uuid4(),
            bid_id=bid_id,
            auction_id=auction_id,
            bidder_id=principal.user_id,
            seller_id=snapshot.seller_id,
            amount=amount,
            currency=snapshot.currency,
            server_seq=resolution.accepted.server_seq,
            accepted_at=accepted_at,
            auction_closes_at=snapshot.closes_at,
            idempotency_key=idempotency_key,
            device_fingerprint=device_fingerprint,
            increment_stale=resolution.increment_stale,
        )
        try:
            await self.publisher.publish(event)
        except Exception as exc:
            logger.exception("Publishing to bid.events failed; rolling back bid %s", bid_id)
            await self.prices.rollback(auction_id, resolution.accepted, resolution.previous)
            raise ApiError(
                "SERVICE_UNAVAILABLE", "The bid could not be recorded; it was not accepted", 503
            ) from exc
        try:
            await self.prices.enqueue_for_flush(event)
        except Exception:
            # Already on Kafka, which is the recovery source: the flusher's replay persists it.
            logger.exception("Queueing bid %s for the flusher failed", bid_id)

        next_threshold = await self._threshold(snapshot, resolution.accepted)
        self.metrics.accepted.inc()
        body = accepted_body(bid_id, auction_id, resolution.accepted.server_seq, amount,
                             next_threshold.min_next_bid, accepted_at)
        return PlaceBidResult(202, body)
