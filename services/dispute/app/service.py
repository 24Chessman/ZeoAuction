"""Dispute service use cases (Plan 6, #84).

Handles window-gated dispute creation, evidence submission, and admin adjudication
with separate outcome and fault inputs. Sends commands to Payment & Escrow.
"""

from collections.abc import Callable
from datetime import UTC, datetime
import logging
from typing import Any
from uuid import UUID, uuid4

from app.adapters.dispute_repo import DisputeRepository
from app.adapters.payment_client import PaymentClient
from app.domain.dispute import (
    Dispute,
    DisputeConflictError,
    DisputeError,
    DisputeEvidence,
    DisputeState,
    EvidenceKind,
    Fault,
    ReasonCode,
    WindowClosedError,
    create_buyer_dispute,
    create_fraud_dispute,
    resolve_dispute as domain_resolve,
    start_review as domain_review,
)
from zeo_common import ApiError
from zeo_common.audit import AuditEntry, AuditWriter

logger = logging.getLogger("dispute.service")


class DisputeService:
    def __init__(
        self,
        repo: DisputeRepository,
        payment_client: PaymentClient,
        audit_writer: AuditWriter,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repo = repo
        self.payment = payment_client
        self.audit = audit_writer
        self.clock = clock

    async def raise_dispute(
        self,
        order_id: UUID,
        user_id: UUID,
        reason_code: str,
        description: str,
        *,
        is_admin: bool = False,
    ) -> Dispute:
        """Buyer raises a dispute against an order during the open protection window."""
        order_info = await self.payment.get_order(order_id)
        if order_info is None:
            raise ApiError("NOT_FOUND", f"Order {order_id} not found", 404)

        if not is_admin and order_info.buyer_id != user_id:
            raise ApiError("FORBIDDEN", "Only the buyer can raise a dispute on this order", 403)

        # Check existing open dispute
        existing_open = await self.repo.get_open_by_order(order_id)
        if existing_open is not None:
            raise ApiError("CONFLICT", f"Order {order_id} already has an open dispute", 409)

        now = self.clock()
        try:
            dispute = create_buyer_dispute(
                order_id=order_id,
                user_id=user_id,
                reason_code=reason_code,
                description=description,
                now=now,
                protection_window_ends_at=order_info.protection_window_ends_at,
            )
        except WindowClosedError as exc:
            raise ApiError("WINDOW_CLOSED", str(exc), 409) from exc
        except (DisputeError, ValueError) as exc:
            raise ApiError("VALIDATION_ERROR", str(exc), 422) from exc

        # Save dispute
        try:
            saved = await self.repo.create_dispute(dispute)
        except DisputeConflictError as exc:
            raise ApiError("CONFLICT", str(exc), 409) from exc

        # Freeze escrow in payment service
        await self.payment.freeze_order(order_id, reason="dispute")
        logger.info("Dispute %s opened for order %s by buyer %s", saved.id, order_id, user_id)
        return saved

    async def open_fraud_dispute(
        self,
        order_id: UUID,
        fraud_alert_id: UUID,
        description: str,
        bid_trace: dict[str, Any] | None = None,
    ) -> Dispute:
        """Automated dispute opened by the Fraud Detector service (#56)."""
        now = self.clock()
        dispute = create_fraud_dispute(order_id, fraud_alert_id, description, now)
        try:
            saved = await self.repo.create_dispute(dispute)
        except DisputeConflictError as exc:
            raise ApiError("CONFLICT", str(exc), 409) from exc

        if bid_trace:
            evidence = DisputeEvidence(
                id=uuid4(),
                dispute_id=saved.id,
                kind=EvidenceKind.BID_TRACE,
                bid_trace=bid_trace,
                submitted_at=now,
            )
            await self.repo.add_evidence(evidence)

        # Freeze escrow in payment service
        await self.payment.freeze_order(order_id, reason="fraud")
        logger.info("Fraud dispute %s opened for order %s", saved.id, order_id)
        return saved

    async def add_evidence(
        self,
        dispute_id: UUID,
        submitted_by: UUID | None,
        kind: str,
        *,
        object_key: str | None = None,
        body: str | None = None,
        bid_trace: dict[str, Any] | None = None,
    ) -> DisputeEvidence:
        dispute = await self.repo.get_dispute(dispute_id)
        if dispute is None:
            raise ApiError("NOT_FOUND", f"Dispute {dispute_id} not found", 404)

        if dispute.state in (DisputeState.RESOLVED_SELLER, DisputeState.RESOLVED_BUYER):
            raise ApiError("CONFLICT", "Cannot add evidence to a resolved dispute", 409)

        try:
            evidence = DisputeEvidence(
                id=uuid4(),
                dispute_id=dispute_id,
                kind=EvidenceKind(kind),
                submitted_by=submitted_by,
                object_key=object_key,
                body=body,
                bid_trace=bid_trace,
                submitted_at=self.clock(),
            )
        except (DisputeError, ValueError) as exc:
            raise ApiError("VALIDATION_ERROR", str(exc), 422) from exc

        return await self.repo.add_evidence(evidence)

    async def start_review(self, dispute_id: UUID, admin_id: UUID) -> Dispute:
        dispute = await self.repo.get_dispute(dispute_id)
        if dispute is None:
            raise ApiError("NOT_FOUND", f"Dispute {dispute_id} not found", 404)

        if dispute.state != DisputeState.OPEN:
            return dispute

        now = self.clock()
        updated = domain_review(dispute, now)
        saved = await self.repo.update_dispute(updated)

        await self.audit.write(
            AuditEntry(
                actor_id=admin_id,
                actor_role="ADMIN",
                service="dispute",
                action="DISPUTE_REVIEW",
                target_type="dispute",
                target_id=dispute_id,
                before_state={"state": dispute.state.value},
                after_state={"state": saved.state.value},
                at=now,
            )
        )
        return saved

    async def resolve_dispute(
        self,
        dispute_id: UUID,
        admin_id: UUID,
        outcome: str,
        fault: str | None,
        note: str,
        *,
        idempotency_key: str | None = None,
    ) -> Dispute:
        """Admin resolves dispute: sends release or refund command to Payment."""
        dispute = await self.repo.get_dispute(dispute_id)
        if dispute is None:
            raise ApiError("NOT_FOUND", f"Dispute {dispute_id} not found", 404)

        # Idempotency check
        if dispute.state in (DisputeState.RESOLVED_SELLER, DisputeState.RESOLVED_BUYER):
            return dispute

        now = self.clock()
        try:
            resolved = domain_resolve(dispute, outcome, fault, note, admin_id, now)
        except (DisputeError, ValueError) as exc:
            raise ApiError("VALIDATION_ERROR", str(exc), 422) from exc

        saved = await self.repo.update_dispute(resolved)

        # Send command to Payment service
        key = idempotency_key or f"dispute:{dispute.id}:resolve"
        if saved.state == DisputeState.RESOLVED_SELLER:
            await self.payment.release_order(dispute.order_id, idempotency_key=key)
        elif saved.state == DisputeState.RESOLVED_BUYER:
            await self.payment.refund_order(
                dispute.order_id,
                fault=saved.fault.value if saved.fault else "SELLER",
                note=note,
                idempotency_key=key,
            )

        # Immutable audit log write
        await self.audit.write(
            AuditEntry(
                actor_id=admin_id,
                actor_role="ADMIN",
                service="dispute",
                action="DISPUTE_RESOLVE",
                target_type="dispute",
                target_id=dispute_id,
                before_state={"state": dispute.state.value},
                after_state={
                    "state": saved.state.value,
                    "fault": saved.fault.value if saved.fault else None,
                },
                reason_code=dispute.reason_code.value,
                note=note,
                at=now,
            )
        )
        logger.info("Dispute %s resolved to %s by admin %s", dispute_id, outcome, admin_id)
        return saved
