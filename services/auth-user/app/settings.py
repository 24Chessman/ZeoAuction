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

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=env_str(
                "DATABASE_URL", "postgresql://auth_svc:auth_dev_pw@localhost:5432/zeoauction"
            ),
            refresh_ttl_days=env_int("REFRESH_TOKEN_TTL_DAYS", 14),
            accept_seed_password=env_bool("AUTH_ACCEPT_SEED_PASSWORD", False),
            seed_password=env_str("AUTH_SEED_PASSWORD", "zeo-dev-password"),
        )
