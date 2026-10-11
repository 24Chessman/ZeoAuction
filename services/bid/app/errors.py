"""The bid rejection taxonomy as code (contracts/errors/bid-rejection-codes.yaml, SDD Table 5.1).

Final in Plan 3 (#21), version :data:`TAXONOMY_VERSION`. ``tests/test_rejections.py`` keeps
this module identical to the published YAML (codes, HTTP statuses, retryability and the
``details`` keys) and drives every code through the API to check it arrives in the uniform
error envelope. Clients switch on the code, never on the message.
"""

from dataclasses import dataclass
from typing import Any

from zeo_common import ApiError

TAXONOMY_VERSION = "1.0.0"


@dataclass(frozen=True)
class Rejection:
    http: int
    retryable: bool = False
    details: tuple[str, ...] = ()


# Every code on the bid path. SELLER_NOT_VERIFIED is the listing path's (zeo_common.gateway).
TAXONOMY: dict[str, Rejection] = {
    "ACCOUNT_SUSPENDED": Rejection(403),
    "SELF_BIDDING_FORBIDDEN": Rejection(403),
    "AUCTION_NOT_OPEN": Rejection(409, details=("state",)),
    "AUCTION_CLOSED": Rejection(409),
    "BID_BELOW_INCREMENT": Rejection(422, details=("min_next_bid",)),
    "INSUFFICIENT_FUNDS": Rejection(402),
    "DUPLICATE_IDEMPOTENCY_KEY": Rejection(200),
    "AUCTION_STATE_UNAVAILABLE": Rejection(503, retryable=True),
}

# code -> HTTP status.
REJECTION_STATUS: dict[str, int] = {code: entry.http for code, entry in TAXONOMY.items()}


class BidRejected(Exception):
    """A bid refused by a business rule. Raised before any state change."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        entry = TAXONOMY.get(code)
        if entry is None:
            raise ValueError(f"{code} is not in the bid rejection taxonomy")
        if set(details or ()) != set(entry.details):
            raise ValueError(f"{code} must carry exactly the details {list(entry.details)}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    @property
    def status_code(self) -> int:
        return REJECTION_STATUS[self.code]

    @property
    def retryable(self) -> bool:
        return TAXONOMY[self.code].retryable

    def to_api_error(self) -> ApiError:
        return ApiError(self.code, self.message, self.status_code, self.details)


def state_unavailable() -> ApiError:
    """Not cached as an idempotent outcome: the same key may be retried (retryable)."""
    return BidRejected(
        "AUCTION_STATE_UNAVAILABLE",
        "Auction state is temporarily unavailable; the bid was not accepted",
    ).to_api_error()
