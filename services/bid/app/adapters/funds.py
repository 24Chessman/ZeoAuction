"""Funds check for FR-BID-2 (``INSUFFICIENT_FUNDS``).

The escrow is a functional simulation and Payment exposes no funds or hold API yet, so the
check is a stub with a configurable per-bidder limit (``STUB_FUNDS_LIMIT``). It keeps the
port shape the real check will have once Payment offers one.
"""

from decimal import Decimal
from typing import Protocol
from uuid import UUID


class FundsPort(Protocol):
    async def available(self, bidder_id: UUID) -> Decimal: ...


class StubFunds:
    def __init__(self, limit: Decimal) -> None:
        self.limit = limit

    async def available(self, bidder_id: UUID) -> Decimal:
        return self.limit
