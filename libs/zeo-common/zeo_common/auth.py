"""Access-token verification shared by every service (ADR-0005, SDD 9.1).

The auth-user service mints 15-minute HS256 access tokens carrying ``sub``, ``role``,
``kyc_status`` and ``suspended``; every other service verifies them locally with the shared
``JWT_SECRET``, so no request makes a call to the auth service. This module verifies the
token; :mod:`zeo_common.gateway` builds the role, KYC and suspension gates of
docs/architecture.md on top of it, as FastAPI dependencies applied per route, so no service
re-implements the checks.

    from zeo_common.auth import CurrentPrincipal

    @router.post("/things")
    async def create(principal: CurrentPrincipal): ...
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Depends, FastAPI, Request

from zeo_common.errors import ApiError
from zeo_common.settings import env_int, env_str

logger = logging.getLogger(__name__)

# LOCAL DEVELOPMENT ONLY. Hosted environments set JWT_SECRET from a Render environment group.
DEV_JWT_SECRET = "zeo-dev-jwt-secret-not-for-production-use"  # noqa: S105

ROLES = ("USER", "ADMIN")
KYC_STATUSES = ("NOT_SUBMITTED", "SUBMITTED", "UNDER_REVIEW", "VERIFIED", "REJECTED", "SUSPENDED")


@dataclass(frozen=True)
class JwtSettings:
    secret: str
    issuer: str = "zeoauction-auth"
    audience: str = "zeoauction"
    algorithm: str = "HS256"
    access_ttl_seconds: int = 15 * 60
    leeway_seconds: int = 5

    @classmethod
    def from_env(cls) -> "JwtSettings":
        secret = env_str("JWT_SECRET", DEV_JWT_SECRET)
        if secret == DEV_JWT_SECRET:
            logger.warning("JWT_SECRET is not set; using the local development secret")
        return cls(secret=secret, access_ttl_seconds=env_int("JWT_ACCESS_TTL_SECONDS", 15 * 60))


@dataclass(frozen=True)
class Principal:
    """The verified caller, built only from the token's claims."""

    user_id: UUID
    role: str
    kyc_status: str
    suspended: bool
    token_version: int = 1

    @property
    def is_admin(self) -> bool:
        return self.role == "ADMIN"


def encode_access_token(
    settings: JwtSettings,
    *,
    user_id: UUID,
    role: str,
    kyc_status: str,
    suspended: bool,
    token_version: int = 1,
    now: datetime | None = None,
) -> str:
    issued = now or datetime.now(UTC)
    claims: dict[str, Any] = {
        "iss": settings.issuer,
        "aud": settings.audience,
        "sub": str(user_id),
        "role": role,
        "kyc_status": kyc_status,
        "suspended": suspended,
        "tv": token_version,
        "typ": "access",
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(seconds=settings.access_ttl_seconds)).timestamp()),
    }
    return jwt.encode(claims, settings.secret, algorithm=settings.algorithm)


def unauthenticated(message: str = "Missing, expired or invalid bearer token") -> ApiError:
    return ApiError("UNAUTHENTICATED", message, 401)


def decode_access_token(settings: JwtSettings, token: str) -> Principal:
    """Verify signature, issuer, audience and expiry, and return the principal.

    Raises :class:`ApiError` ``UNAUTHENTICATED`` for any defect; the reason is logged, not
    returned, so a caller learns nothing about why a token was refused.
    """
    try:
        claims = jwt.decode(
            token,
            settings.secret,
            algorithms=[settings.algorithm],
            audience=settings.audience,
            issuer=settings.issuer,
            leeway=settings.leeway_seconds,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
        if claims.get("typ") != "access":
            raise jwt.InvalidTokenError("not an access token")
        if claims.get("role") not in ROLES or claims.get("kyc_status") not in KYC_STATUSES:
            raise jwt.InvalidTokenError("unknown role or kyc_status claim")
        if not isinstance(claims.get("suspended"), bool):
            raise jwt.InvalidTokenError("suspended claim must be a boolean")
        return Principal(
            user_id=UUID(claims["sub"]),
            role=claims["role"],
            kyc_status=claims["kyc_status"],
            suspended=claims["suspended"],
            token_version=int(claims.get("tv", 1)),
        )
    except (jwt.InvalidTokenError, ValueError, TypeError) as exc:
        logger.info("Rejected access token: %s", exc)
        raise unauthenticated() from exc


def install_auth(app: FastAPI, settings: JwtSettings | None = None) -> None:
    """Make :data:`CurrentPrincipal` work on ``app``'s routes."""
    app.state.jwt_settings = settings or JwtSettings.from_env()


def bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise unauthenticated()
    return token.strip()


async def current_principal(request: Request) -> Principal:
    settings: JwtSettings | None = getattr(request.app.state, "jwt_settings", None)
    if settings is None:
        raise RuntimeError("install_auth(app) was not called for this service")
    return decode_access_token(settings, bearer_token(request))


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


async def require_admin(principal: CurrentPrincipal) -> Principal:
    if not principal.is_admin:
        raise ApiError("FORBIDDEN", "Administrator role required", 403)
    return principal


AdminPrincipal = Annotated[Principal, Depends(require_admin)]
