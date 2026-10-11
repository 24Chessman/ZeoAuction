"""Payment & Escrow settings, read once at start-up.

Razorpay keys are **test keys only** (``rzp_test_...``) and come from the environment: Compose
locally (``.env``, never committed) and Render environment groups when hosted. Without them the
service runs on the deterministic mock adapter, which is the default locally and in CI.
"""

from dataclasses import dataclass

from zeo_common.settings import SettingsError, env_bool, env_float, env_int, env_str

# LOCAL DEVELOPMENT ONLY: the token Auction Orchestration presents on the internal settlement
# route. Hosted environments set INTERNAL_SERVICE_TOKEN from a Render environment group.
DEV_INTERNAL_TOKEN = "zeo-dev-internal-token-not-for-production"  # noqa: S105


@dataclass(frozen=True)
class Settings:
    database_url: str
    # "postgres" in Compose and on Render; "memory" for local runs without a database.
    repository: str
    kafka_bootstrap_servers: str
    # "kafka" in Compose and on Render; "memory" for local runs without a broker.
    publisher: str = "memory"
    # "mock" (default, offline and deterministic) or "razorpay" (test mode, ADR-0009).
    payment_adapter: str = "mock"
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    # Route linked account that receives seller payouts in test mode (acc_...). One demo
    # account stands in for every seller until sellers onboard their own (Plan 6).
    razorpay_linked_account: str = ""
    internal_token: str = DEV_INTERNAL_TOKEN
    # The winner must authorise payment within this (settlement-policy checkout).
    payment_window_hours: int = 48
    # Retry parked captures and expire unpaid orders in this process.
    run_settlement_worker: bool = False
    worker_interval_seconds: float = 5.0

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            database_url=env_str(
                "DATABASE_URL", "postgresql://payment_svc:payment_dev_pw@localhost:5432/zeoauction"
            ),
            repository=env_str("PAYMENT_REPOSITORY", "postgres"),
            kafka_bootstrap_servers=env_str("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092"),
            publisher=env_str("PAYMENT_PUBLISHER", "kafka"),
            payment_adapter=env_str("PAYMENT_ADAPTER", "mock"),
            razorpay_key_id=env_str("RAZORPAY_KEY_ID", ""),
            razorpay_key_secret=env_str("RAZORPAY_KEY_SECRET", ""),
            razorpay_webhook_secret=env_str("RAZORPAY_WEBHOOK_SECRET", ""),
            razorpay_linked_account=env_str("RAZORPAY_LINKED_ACCOUNT", ""),
            internal_token=env_str("INTERNAL_SERVICE_TOKEN", DEV_INTERNAL_TOKEN),
            payment_window_hours=env_int("PAYMENT_WINDOW_HOURS", 48),
            run_settlement_worker=env_bool("RUN_SETTLEMENT_WORKER", True),
            worker_interval_seconds=env_float("SETTLEMENT_WORKER_INTERVAL_SECONDS", 5.0),
        )
        if settings.payment_adapter not in ("mock", "razorpay"):
            raise SettingsError("PAYMENT_ADAPTER must be 'mock' or 'razorpay'")
        return settings
