"""Auction Orchestration use cases: listing, lifecycle transitions, timers, bids, settlement.

Every transition goes through :func:`app.domain.lifecycle.transition`, is saved with the
version check, recorded in ``auction_state_transitions``, and then published to
``auction.events``. Publishing happens after the commit: if the broker is down the transition
stands and the failure is logged and counted (``auction_events_publish_failures``).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from prometheus_client import CollectorRegistry, Counter

from app.adapters.auction_repo import AuctionRepository, StaleAuction
from app.adapters.kafka_producer import AuctionEventPublisher, build_state_changed
from app.adapters.payment_client import PaymentClient, PaymentUnavailable, SettlementRefused
from app.adapters.payment_events import SettlementStep
from app.domain.anti_snipe import AcceptedBid, apply_bid
from app.domain.auction import Auction, AuctionValidationError, new_draft
from app.domain.lifecycle import SYSTEM, Actor, GuardFailed, IllegalTransition, transition
from app.domain.settlement import NotSettleable, record_order, settlement_request
from zeo_common import ApiError
from zeo_common.auth import Principal

logger = logging.getLogger(__name__)

# States in which an accepted bid may still arrive: open for bidding, or closing while the
# bids accepted before the deadline drain in (A5 -> A6).
BID_RECORDING_STATES = frozenset({"OPEN", "EXTENDED", "CLOSING"})
MAX_BID_ATTEMPTS = 5


class AuctionMetrics:
    def __init__(self, registry: CollectorRegistry) -> None:
        self.transitions = Counter(
            "auction_transitions", "Accepted lifecycle transitions, by event.", ["event"],
            registry=registry,
        )
        self.publish_failures = Counter(
            "auction_events_publish_failures",
            "Transitions committed but not published to auction.events.", registry=registry,
        )
        self.settlement_deferred = Counter(
            "auction_settlement_deferred",
            "Order opening deferred because Payment was unavailable or refused (CT-4).",
            ["reason"], registry=registry,
        )


@dataclass(frozen=True)
class Draft:
    title: str
    description: str
    category: str
    starting_price: Decimal
    reserve_price: Decimal | None
    currency: str
    opens_at: datetime | None
    closes_at: datetime | None


def actor_of(principal: Principal) -> Actor:
    return Actor(user_id=principal.user_id, is_admin=principal.is_admin)


def to_api_error(error: Exception) -> ApiError:
    if isinstance(error, IllegalTransition):
        return ApiError("CONFLICT", str(error), 409, {"state": error.state, "event": error.event})
    if isinstance(error, GuardFailed):
        return ApiError(error.code, error.message, error.status, error.details)
    if isinstance(error, StaleAuction):
        return ApiError("CONFLICT", "Auction changed concurrently; retry", 409)
    raise error


class AuctionService:
    def __init__(
        self,
        repo: AuctionRepository,
        publisher: AuctionEventPublisher,
        metrics: AuctionMetrics,
        *,
        drain_grace: timedelta = timedelta(seconds=5),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        payment: PaymentClient | None = None,
    ) -> None:
        self.repo = repo
        self.publisher = publisher
        self.metrics = metrics
        self.drain_grace = drain_grace
        self.clock = clock
        # None where settlement is not wired (local runs without Payment): auctions then stay
        # CLOSED until an administrator settles them.
        self.payment = payment

    async def load(self, auction_id: UUID) -> Auction:
        auction = await self.repo.get(auction_id)
        if auction is None:
            raise ApiError("NOT_FOUND", f"Auction {auction_id} does not exist", 404)
        return auction

    async def _announce(self, before: Auction, after: Auction, event: str,
                        actor_id: UUID | None) -> None:
        self.metrics.transitions.labels(event=event).inc()
        payload = build_state_changed(
            event_id=uuid4(), before=before, after=after, event=event, actor_id=actor_id,
            occurred_at=after.updated_at,
        )
        try:
            await self.publisher.publish(payload)
        except Exception:
            self.metrics.publish_failures.inc()
            logger.exception("Publishing %s for auction %s failed", event, after.id)

    async def _apply(self, before: Auction, event: str, actor: Actor) -> Auction:
        after = transition(before, event, now=self.clock(), actor=actor)
        await self.repo.save_transition(before, after, event, actor.user_id)
        await self._announce(before, after, event, actor.user_id)
        return after

    # ------------------------------------------------------------------ users

    async def create(self, seller: Principal, draft: Draft) -> Auction:
        """Create a DRAFT. The route has already passed the listing gate (CT-2)."""
        try:
            auction = new_draft(
                auction_id=uuid4(), seller_id=seller.user_id, title=draft.title,
                description=draft.description, category=draft.category,
                starting_price=draft.starting_price, reserve_price=draft.reserve_price,
                currency=draft.currency, opens_at=draft.opens_at, closes_at=draft.closes_at,
                now=self.clock(),
            )
        except AuctionValidationError as exc:
            raise ApiError("VALIDATION_ERROR", str(exc), 422) from exc
        await self.repo.add(auction)
        return auction

    async def apply(self, principal: Principal, auction_id: UUID, event: str) -> Auction:
        """A user- or admin-initiated transition; a lost race is a 409 the client retries."""
        before = await self.load(auction_id)
        try:
            return await self._apply(before, event, actor_of(principal))
        except (IllegalTransition, GuardFailed, StaleAuction) as exc:
            raise to_api_error(exc) from exc

    # ------------------------------------------------------------------ platform

    async def tick(self, limit: int = 100) -> list[tuple[UUID, str]]:
        """One pass of the lifecycle timer: open, close and drain whatever is due, then hand
        closed auctions to Payment."""
        done = await self._tick_transitions(limit)
        for auction_id in await self.settle_pending(limit):
            done.append((auction_id, "invoice"))
        return done

    async def _tick_transitions(self, limit: int) -> list[tuple[UUID, str]]:
        done = []
        for auction, event in await self.repo.due(self.clock(), self.drain_grace, limit):
            try:
                await self._apply(auction, event, SYSTEM)
            except (StaleAuction, GuardFailed, IllegalTransition) as exc:
                # Another instance or a bid got there first; the next tick re-reads.
                logger.info("Timer %s on auction %s deferred: %s", event, auction.id, exc)
                continue
            done.append((auction.id, event))
        return done

    async def on_bid_accepted(self, bid: AcceptedBid) -> bool:
        """Record the leader and apply anti-snipe. Returns whether the auction was extended."""
        for _ in range(MAX_BID_ATTEMPTS):
            before = await self.repo.get(bid.auction_id)
            if before is None:
                logger.warning("Bid %s refers to unknown auction %s", bid.bid_id, bid.auction_id)
                return False
            if before.state not in BID_RECORDING_STATES:
                if bid.server_seq > before.last_bid_seq:
                    logger.warning("Bid %s arrived for auction %s in state %s; ignored",
                                   bid.bid_id, before.id, before.state)
                return False
            outcome = apply_bid(before, bid, self.clock())
            if outcome.duplicate:
                return False
            try:
                if outcome.extended:
                    await self.repo.save_transition(before, outcome.auction, "extend", None)
                    await self._announce(before, outcome.auction, "extend", None)
                else:
                    await self.repo.record_bid(before, outcome.auction)
            except StaleAuction:
                continue  # a timer or another event moved the row; re-read and re-apply
            return outcome.extended
        raise StaleAuction(str(bid.auction_id))

    # ------------------------------------------------------------------ settlement (#33)

    async def settle_pending(self, limit: int = 100) -> list[UUID]:
        """S1 for every CLOSED auction with a winner and no order: Payment opens the order and
        invoice. A failure leaves the auction CLOSED for the next pass (deferred, never
        abandoned); while the breaker is open the pass stops early instead of failing fast
        once per auction."""
        if self.payment is None:
            return []
        opened = []
        for auction in await self.repo.awaiting_settlement(limit):
            try:
                order_id = await self.payment.open_order(settlement_request(auction))
            except PaymentUnavailable as exc:
                self.metrics.settlement_deferred.labels(reason="unavailable").inc()
                logger.warning("Opening the order for auction %s deferred: %s", auction.id, exc)
                break
            except (SettlementRefused, NotSettleable) as exc:
                self.metrics.settlement_deferred.labels(reason="refused").inc()
                logger.error("Payment refused to settle auction %s: %s", auction.id, exc)
                continue
            try:
                await self.repo.record_settlement(
                    auction, record_order(auction, order_id, self.clock()))
            except StaleAuction:
                continue  # re-read next pass; Payment returns the same order (idempotent)
            opened.append(auction.id)
        return opened

    async def on_settlement_step(self, step: SettlementStep) -> bool:
        """A7 ``settle`` once Payment reports the order HELD in escrow. Returns whether the
        auction moved; a redelivery or an already SETTLED auction changes nothing."""
        if step.type != "HELD":
            return False
        for _ in range(MAX_BID_ATTEMPTS):
            auction = await self.repo.get(step.auction_id)
            if auction is None:
                logger.warning("Order %s refers to unknown auction %s", step.order_id,
                               step.auction_id)
                return False
            if auction.state != "CLOSED":
                return False
            if auction.settlement_order_id is None:
                # HELD overtook our own record of the order; remember it on the way.
                auction = await self._remember_order(auction, step.order_id)
                if auction is None:
                    continue
            try:
                await self._apply(auction, "settle", SYSTEM)
            except StaleAuction:
                continue
            return True
        raise StaleAuction(str(step.auction_id))

    async def _remember_order(self, auction: Auction, order_id: UUID) -> Auction | None:
        after = record_order(auction, order_id, self.clock())
        try:
            await self.repo.record_settlement(auction, after)
        except StaleAuction:
            return None
        return after
