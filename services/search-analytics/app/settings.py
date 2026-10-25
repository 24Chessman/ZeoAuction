"""Search & Analytics service configuration (Plan 6, #46, #47, #75)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    payment_service_url: str = "http://payment-escrow:8000"
    internal_service_token: str = "dev-token"
    repository: str = "memory"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL", ""),
            payment_service_url=os.getenv(
                "PAYMENT_SERVICE_URL", "http://payment-escrow:8000"
            ),
            internal_service_token=os.getenv("INTERNAL_SERVICE_TOKEN", "dev-token"),
            repository=os.getenv("SEARCH_REPOSITORY", "memory"),
        )
