"""Dispute service configuration (Plan 6, #84)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    repository: str = "memory"
    payment_service_url: str = "http://payment-escrow:8000"
    internal_token: str = "dispute-internal-token-change-in-prod"
    kafka_bootstrap_servers: str = "localhost:9092"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL", ""),
            repository=os.getenv("DISPUTE_REPOSITORY", "memory"),
            payment_service_url=os.getenv("PAYMENT_SERVICE_URL", "http://payment-escrow:8000"),
            internal_token=os.getenv("INTERNAL_SERVICE_TOKEN", "dispute-internal-token-change-in-prod"),
            kafka_bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        )
