"""Dispute repository: persists disputes and evidence (Plan 6, #84).

Database schema: infra/postgres/init/70-dispute.sql
"""

from collections import defaultdict
from typing import Any, Protocol
from uuid import UUID

from app.domain.dispute import (
    Dispute,
    DisputeConflictError,
    DisputeEvidence,
    DisputeState,
    EvidenceKind,
    Fault,
    OpenedBy,
    ReasonCode,
)


class DisputeRepository(Protocol):
    async def create_dispute(self, dispute: Dispute) -> Dispute: ...
    async def get_dispute(self, dispute_id: UUID) -> Dispute | None: ...
    async def get_by_order(self, order_id: UUID) -> list[Dispute]: ...
    async def get_open_by_order(self, order_id: UUID) -> Dispute | None: ...
    async def update_dispute(self, dispute: Dispute) -> Dispute: ...
    async def list_disputes(self, state: str | None = None) -> list[Dispute]: ...
    async def add_evidence(self, evidence: DisputeEvidence) -> DisputeEvidence: ...
    async def get_evidence(self, dispute_id: UUID) -> list[DisputeEvidence]: ...


class InMemoryDisputeRepository:
    def __init__(self) -> None:
        self.disputes: dict[UUID, Dispute] = {}
        self.evidence: dict[UUID, list[DisputeEvidence]] = defaultdict(list)

    async def create_dispute(self, dispute: Dispute) -> Dispute:
        # Enforce unique index: at most one open/under_review dispute per order
        for d in self.disputes.values():
            if d.order_id == dispute.order_id and d.state in (DisputeState.OPEN, DisputeState.UNDER_REVIEW):
                raise DisputeConflictError(f"Order {dispute.order_id} already has an open dispute")
        self.disputes[dispute.id] = dispute
        return dispute

    async def get_dispute(self, dispute_id: UUID) -> Dispute | None:
        return self.disputes.get(dispute_id)

    async def get_by_order(self, order_id: UUID) -> list[Dispute]:
        return [d for d in self.disputes.values() if d.order_id == order_id]

    async def get_open_by_order(self, order_id: UUID) -> Dispute | None:
        for d in self.disputes.values():
            if d.order_id == order_id and d.state in (DisputeState.OPEN, DisputeState.UNDER_REVIEW):
                return d
        return None

    async def update_dispute(self, dispute: Dispute) -> Dispute:
        self.disputes[dispute.id] = dispute
        return dispute

    async def list_disputes(self, state: str | None = None) -> list[Dispute]:
        if state is not None:
            return [d for d in self.disputes.values() if d.state == state]
        return list(self.disputes.values())

    async def add_evidence(self, evidence: DisputeEvidence) -> DisputeEvidence:
        self.evidence[evidence.dispute_id].append(evidence)
        return evidence

    async def get_evidence(self, dispute_id: UUID) -> list[DisputeEvidence]:
        return list(self.evidence.get(dispute_id, []))


class PostgresDisputeRepository:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def create_dispute(self, dispute: Dispute) -> Dispute:
        query = (
            "INSERT INTO dispute.disputes (id, order_id, opened_by, opened_by_user_id, "
            "fraud_alert_id, reason_code, description, state, fault, resolution_note, "
            "resolved_by, resolved_at, opened_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)"
        )
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    query,
                    dispute.id,
                    dispute.order_id,
                    str(dispute.opened_by),
                    dispute.opened_by_user_id,
                    dispute.fraud_alert_id,
                    str(dispute.reason_code),
                    dispute.description,
                    str(dispute.state),
                    str(dispute.fault) if dispute.fault else None,
                    dispute.resolution_note,
                    dispute.resolved_by,
                    dispute.resolved_at,
                    dispute.opened_at,
                    dispute.updated_at,
                )
            except Exception as e:
                if "disputes_one_open_per_order" in str(e):
                    raise DisputeConflictError(f"Order {dispute.order_id} already has an open dispute") from e
                raise
        return dispute

    async def get_dispute(self, dispute_id: UUID) -> Dispute | None:
        query = "SELECT * FROM dispute.disputes WHERE id = $1"
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, dispute_id)
            return self._row_to_dispute(row) if row else None

    async def get_by_order(self, order_id: UUID) -> list[Dispute]:
        query = "SELECT * FROM dispute.disputes WHERE order_id = $1 ORDER BY opened_at DESC"
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, order_id)
            return [self._row_to_dispute(r) for r in rows]

    async def get_open_by_order(self, order_id: UUID) -> Dispute | None:
        query = (
            "SELECT * FROM dispute.disputes WHERE order_id = $1 AND state IN ('OPEN', 'UNDER_REVIEW')"
        )
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, order_id)
            return self._row_to_dispute(row) if row else None

    async def update_dispute(self, dispute: Dispute) -> Dispute:
        query = (
            "UPDATE dispute.disputes SET state = $1, fault = $2, resolution_note = $3, "
            "resolved_by = $4, resolved_at = $5, updated_at = $6 WHERE id = $7"
        )
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                str(dispute.state),
                str(dispute.fault) if dispute.fault else None,
                dispute.resolution_note,
                dispute.resolved_by,
                dispute.resolved_at,
                dispute.updated_at,
                dispute.id,
            )
        return dispute

    async def list_disputes(self, state: str | None = None) -> list[Dispute]:
        if state:
            query = "SELECT * FROM dispute.disputes WHERE state = $1 ORDER BY opened_at DESC"
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, state)
        else:
            query = "SELECT * FROM dispute.disputes ORDER BY opened_at DESC"
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
        return [self._row_to_dispute(r) for r in rows]

    async def add_evidence(self, evidence: DisputeEvidence) -> DisputeEvidence:
        query = (
            "INSERT INTO dispute.dispute_evidence (id, dispute_id, kind, object_key, bid_trace, "
            "body, submitted_by, submitted_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)"
        )
        import json
        trace_json = json.dumps(evidence.bid_trace) if evidence.bid_trace else None
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                evidence.id,
                evidence.dispute_id,
                str(evidence.kind),
                evidence.object_key,
                trace_json,
                evidence.body,
                evidence.submitted_by,
                evidence.submitted_at,
            )
        return evidence

    async def get_evidence(self, dispute_id: UUID) -> list[DisputeEvidence]:
        query = "SELECT * FROM dispute.dispute_evidence WHERE dispute_id = $1 ORDER BY submitted_at ASC"
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, dispute_id)
            import json
            results = []
            for r in rows:
                trace = json.loads(r["bid_trace"]) if r["bid_trace"] else None
                results.append(
                    DisputeEvidence(
                        id=r["id"],
                        dispute_id=r["dispute_id"],
                        kind=EvidenceKind(r["kind"]),
                        object_key=r["object_key"],
                        bid_trace=trace,
                        body=r["body"],
                        submitted_by=r["submitted_by"],
                        submitted_at=r["submitted_at"],
                    )
                )
            return results

    @staticmethod
    def _row_to_dispute(row: Any) -> Dispute:
        return Dispute(
            id=row["id"],
            order_id=row["order_id"],
            opened_by=OpenedBy(row["opened_by"]),
            opened_by_user_id=row["opened_by_user_id"],
            fraud_alert_id=row["fraud_alert_id"],
            reason_code=ReasonCode(row["reason_code"]),
            description=row["description"],
            state=DisputeState(row["state"]),
            fault=Fault(row["fault"]) if row["fault"] else None,
            resolution_note=row["resolution_note"],
            resolved_by=row["resolved_by"],
            resolved_at=row["resolved_at"],
            opened_at=row["opened_at"],
            updated_at=row["updated_at"],
        )
