"""Admin service configuration (Plan 6, #81, #82, #83)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    repository: str = "memory"
    redis_url: str = "redis://localhost:6379"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL", ""),
            repository=os.getenv("ADMIN_REPOSITORY", "memory"),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
        )
