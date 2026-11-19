"""Auth & User Service settings, read once at start-up."""

from dataclasses import dataclass

from zeo_common.settings import env_bool, env_int, env_str


@dataclass(frozen=True)
class Settings:
    database_url: str
    refresh_ttl_days: int
    # LOCAL DEVELOPMENT ONLY: lets the seeded accounts (password_hash "!seed") log in with the
    # documented dev password, re-hashing it on first use. Never enabled on Render.
    accept_seed_password: bool
    seed_password: str
    database_schema: str = "auth"
    gmail_user: str = ""
    gmail_password: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_use_tls: bool = True
    frontend_url: str = "http://localhost:5173"
    brevo_api_key: str = ""
    brevo_sender_email: str = ""
    brevo_sender_name: str = "ZeoAuction"

    @classmethod
    def from_env(cls) -> "Settings":
        gmail_user = env_str("GMAIL_USER", "") or env_str("GMAIL_ID", "")
        gmail_password = env_str("GMAIL_PASSWORD", "") or env_str("GMAIL_APP_PASSWORD", "")
        return cls(
            database_url=env_str(
                "DATABASE_URL", "postgresql://auth_svc:auth_dev_pw@localhost:5432/zeoauction"
            ),
            database_schema=env_str("DATABASE_SCHEMA", "auth"),
            refresh_ttl_days=env_int("REFRESH_TOKEN_TTL_DAYS", 14),
            accept_seed_password=env_bool("AUTH_ACCEPT_SEED_PASSWORD", False),
            seed_password=env_str("AUTH_SEED_PASSWORD", "zeo-dev-password"),
            gmail_user=gmail_user,
            gmail_password=gmail_password,
            smtp_host=env_str("SMTP_HOST", "smtp.gmail.com"),
            smtp_port=env_int("SMTP_PORT", 587),
            smtp_use_tls=env_bool("SMTP_USE_TLS", True),
            frontend_url=env_str("FRONTEND_URL", "http://localhost:5173"),
            # BRAVE_API_KEY is accepted as a compatibility alias for an easy-to-make typo.
            brevo_api_key=env_str("BREVO_API_KEY", "") or env_str("BRAVE_API_KEY", ""),
            brevo_sender_email=env_str("BREVO_SENDER_EMAIL", "") or gmail_user,
            brevo_sender_name=env_str("BREVO_SENDER_NAME", "ZeoAuction"),
        )
