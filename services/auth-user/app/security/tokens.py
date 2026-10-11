"""Token minting (#91, ADR-0005, SDD 9.1).

Access tokens: 15-minute HS256 JWTs carrying ``sub``, ``role``, ``kyc_status`` and
``suspended`` (minted with ``zeo_common.auth`` so every service verifies the same shape).
Refresh tokens: opaque random strings; only their SHA-256 is stored, so a database leak does
not leak usable tokens.
"""

import hashlib
import secrets
from datetime import datetime

from app.domain.users import User
from zeo_common.auth import JwtSettings, encode_access_token

REFRESH_TOKEN_BYTES = 32


def mint_access_token(settings: JwtSettings, user: User, now: datetime | None = None) -> str:
    return encode_access_token(
        settings,
        user_id=user.id,
        role=user.role,
        kyc_status=user.kyc_status,
        suspended=user.suspended,
        token_version=user.token_version,
        now=now,
    )


def new_refresh_token() -> str:
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
