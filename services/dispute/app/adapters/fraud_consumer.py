"""Consumer for fraud.alerts: automatically opens disputes on fraud alerts (#56, Plan 6).

FR-DISP-6, AC-14:
A flagged auction opens a dispute with opened_by = FRAUD_SERVICE, links fraud_alert_id,
attaches the bid trace / signals as evidence, and blocks settlement (freezes escrow).
"""

import json
import logging
from typing import Any
from uuid import UUID

from app.domain.dispute import Dispute
from app.service import DisputeService

logger = logging.getLogger("dispute.fraud_consumer")


class FraudAlertConsumer:
    def __init__(self, service: DisputeService) -> None:
        self.service = service

    async def handle_alert(self, alert_data: dict[str, Any], order_id: UUID) -> Dispute:
        """Handle a ShillAlert v1 message for an auction order."""
        alert_id = UUID(alert_data["alert_id"])
        score = alert_data.get("score", 0.0)
        ring_id = alert_data.get("ring_id")

        description = (
            f"Automated fraud alert {alert_id} (score: {score:.2f}, "
            f"ring: {ring_id or 'none'})"
        )
        bid_trace = {
            "signals": alert_data.get("signals", {}),
            "suspect_bidder_ids": alert_data.get("suspect_bidder_ids", []),
            "ring_id": ring_id,
            "raised_at": alert_data.get("raised_at"),
            "score": score,
        }

        dispute = await self.service.open_fraud_dispute(
            order_id=order_id,
            fraud_alert_id=alert_id,
            description=description,
            bid_trace=bid_trace,
        )
        logger.info("Opened fraud dispute %s for alert %s on order %s", dispute.id, alert_id, order_id)
        return dispute

    async def handle_message(self, message: bytes | str, order_id: UUID) -> Dispute:
        data = json.loads(message) if isinstance(message, bytes | str) else message
        return await self.handle_alert(data, order_id)
