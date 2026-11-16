"""Shared Kafka connection settings for all ZeoAuction services.

Reads SASL/SSL configuration from the environment and returns the kwargs dict
that every aiokafka producer/consumer ``connect()`` factory must pass through.

For Aiven (and other SASL_SSL brokers):
    KAFKA_SECURITY_PROTOCOL=SASL_SSL
    KAFKA_SASL_MECHANISM=SCRAM-SHA-256
    KAFKA_SASL_USERNAME=avnadmin
    KAFKA_SASL_PASSWORD=<password>

For plain local Kafka (default):
    KAFKA_SECURITY_PROTOCOL not set  →  PLAINTEXT

SSL CA verification uses Python's system trust store.
"""

import os
import ssl
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class KafkaSettings:
    """SASL/SSL Kafka connection parameters, read from the environment once."""

    bootstrap_servers: str
    security_protocol: str = "PLAINTEXT"
    sasl_mechanism: str = ""
    sasl_plain_username: str = ""
    sasl_plain_password: str = ""
    @classmethod
    def from_env(cls) -> "KafkaSettings":
        return cls(
            bootstrap_servers=os.environ.get(
                "KAFKA_BOOTSTRAP_SERVERS", "localhost:29092"
            ),
            security_protocol=os.environ.get("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT"),
            sasl_mechanism=os.environ.get("KAFKA_SASL_MECHANISM", ""),
            sasl_plain_username=os.environ.get("KAFKA_SASL_USERNAME", ""),
            sasl_plain_password=os.environ.get("KAFKA_SASL_PASSWORD", ""),
        )

    def _ssl_context(self) -> ssl.SSLContext | None:
        """Build an SSL context for SASL_SSL / SSL protocols."""
        if self.security_protocol not in ("SASL_SSL", "SSL"):
            return None
        return ssl.create_default_context()

    def producer_kwargs(self) -> dict[str, Any]:
        """Extra kwargs to pass to ``AIOKafkaProducer(**producer_kwargs())``."""
        kwargs: dict[str, Any] = {}
        protocol = self.security_protocol.upper()
        if protocol in ("SASL_SSL", "SASL_PLAINTEXT"):
            kwargs["security_protocol"] = protocol
            if self.sasl_mechanism:
                kwargs["sasl_mechanism"] = self.sasl_mechanism
            if self.sasl_plain_username:
                kwargs["sasl_plain_username"] = self.sasl_plain_username
            if self.sasl_plain_password:
                kwargs["sasl_plain_password"] = self.sasl_plain_password
        if protocol in ("SASL_SSL", "SSL"):
            kwargs["security_protocol"] = protocol
            ctx = self._ssl_context()
            if ctx is not None:
                kwargs["ssl_context"] = ctx
        return kwargs

    def consumer_kwargs(self) -> dict[str, Any]:
        """Extra kwargs to pass to ``AIOKafkaConsumer(**consumer_kwargs())``."""
        return self.producer_kwargs()
