"""Gateway middleware: role, KYC-status and suspension gating from the JWT (#95, CT-2).

One set of FastAPI dependencies, so no service re-implements the checks
(docs/architecture.md section 1). Everything is decided from the verified token's claims;
nothing on the hot path calls another service (ADR-0005).

    from zeo_common.gateway import VerifiedSeller

    @router.post("/auctions")
    async def create(principal: VerifiedSeller): ...

**Forced token refresh.** Access tokens carry ``tv``, the account's ``token_version``. The
KYC service bumps the version whenever it changes ``kyc_status`` and publishes it to Redis as
``tv:{user_id}`` (:class:`RedisTokenVersions`). Gates that need a fresh claim
(:func:`require_fresh`) refuse a token whose ``tv`` is older with ``401 UNAUTHENTICATED`` and
``details.reason = TOKEN_STALE``; the client refreshes and retries, and the new token carries
the new status. Without this, an approval or a suspension would take up to 15 minutes to reach
the listing gate (services/kyc/docs/design.md section 5).
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Protocol
from uuid import UUID

from fastapi import Depends, FastAPI, Request

from zeo_common.auth import CurrentPrincipal, Principal
from zeo_common.errors import ApiError

logger = logging.getLogger(__name__)

TOKEN_VERSION_TTL_SECONDS = 24 * 60 * 60  # far longer than any access token lives
TOKEN_STALE = "TOKEN_STALE"  # noqa: S105 - a reason code, not a secret


class TokenVersions(Protocol):
    async def current(self, user_id: UUID) -> int | None:
        """The account's latest ``token_version``, or ``None`` if nothing was published."""
        ...


class TokenVersionPublisher(Protocol):
    async def publish(self, user_id: UUID, version: int) -> None: ...


def token_version_key(user_id: UUID) -> str:
    return f"tv:{user_id}"


class RedisTokenVersions:
    """Reader and writer of ``tv:{user_id}``. Rebuildable: a missing key means "no change
    since the token was minted", and the claim itself is still verified."""

    def __init__(self, redis: Any, ttl_seconds: int = TOKEN_VERSION_TTL_SECONDS) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    async def current(self, user_id: UUID) -> int | None:
        raw = await self.redis.get(token_version_key(user_id))
        return None if raw is None else int(raw)

    async def publish(self, user_id: UUID, version: int) -> None:
        # Never move backwards: a delayed write of an older version must not hide a newer one.
        script = (
            "local cur = tonumber(redis.call('GET', KEYS[1]) or '0') "
            "if tonumber(ARGV[1]) > cur then "
            "redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2]) end "
            "return 1"
        )
        await self.redis.eval(script, 1, token_version_key(user_id), version, self.ttl_seconds)


class InMemoryTokenVersions:
    def __init__(self) -> None:
        self.versions: dict[UUID, int] = {}
        self.fail = False

    async def current(self, user_id: UUID) -> int | None:
        if self.fail:
            raise ConnectionError("token version store unavailable")
        return self.versions.get(user_id)

    async def publish(self, user_id: UUID, version: int) -> None:
        self.versions[user_id] = max(version, self.versions.get(user_id, 0))


def install_gateway(app: FastAPI, token_versions: TokenVersions | None) -> None:
    """Enable the freshness check. Without a store, :func:`require_fresh` checks claims only."""
    app.state.token_versions = token_versions


def token_stale() -> ApiError:
    return ApiError(
        "UNAUTHENTICATED",
        "Your account status changed; refresh the access token and retry",
        401,
        {"reason": TOKEN_STALE},
    )


async def check_fresh(principal: Principal, token_versions: TokenVersions | None) -> None:
    if token_versions is None:
        return
    try:
        current = await token_versions.current(principal.user_id)
    except Exception as exc:
        # Fail closed: a gate that cannot tell whether the claim is current refuses.
        logger.warning("Token version lookup failed: %s", type(exc).__name__)
        raise ApiError(
            "SERVICE_UNAVAILABLE", "Account status could not be confirmed; retry shortly", 503
        ) from exc
    if current is not None and principal.token_version < current:
        raise token_stale()


async def require_fresh(request: Request, principal: CurrentPrincipal) -> Principal:
    await check_fresh(principal, getattr(request.app.state, "token_versions", None))
    return principal


FreshPrincipal = Annotated[Principal, Depends(require_fresh)]


def account_suspended() -> ApiError:
    return ApiError("ACCOUNT_SUSPENDED", "This account is suspended", 403)


def seller_not_verified(kyc_status: str) -> ApiError:
    return ApiError(
        "SELLER_NOT_VERIFIED",
        "Seller verification (KYC) must be approved before listing",
        403,
        {"kyc_status": kyc_status},
    )


async def require_active(principal: CurrentPrincipal) -> Principal:
    if principal.suspended:
        raise account_suspended()
    return principal


ActivePrincipal = Annotated[Principal, Depends(require_active)]


def check_verified_seller(principal: Principal) -> None:
    """The listing gate's rule (CT-2, AC-06), usable outside a request too."""
    if principal.suspended:
        raise account_suspended()
    if principal.kyc_status != "VERIFIED":
        raise seller_not_verified(principal.kyc_status)


async def require_verified_seller(principal: FreshPrincipal) -> Principal:
    # Freshness first: a seller approved a minute ago holds a NOT_SUBMITTED token, and must be
    # told to refresh rather than told they are not verified.
    check_verified_seller(principal)
    return principal


VerifiedSeller = Annotated[Principal, Depends(require_verified_seller)]


def require_roles(*roles: str) -> Callable[[Principal], Awaitable[Principal]]:
    """``Depends(require_roles("ADMIN"))``: a role gate with the platform's FORBIDDEN code."""
    allowed = frozenset(roles)

    async def dependency(principal: CurrentPrincipal) -> Principal:
        if principal.role not in allowed:
            raise ApiError("FORBIDDEN", f"Requires role {' or '.join(sorted(allowed))}", 403)
        return principal

    return dependency
