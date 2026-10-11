"""Auth & User Service routes (SDD 7.2): register, login, refresh, logout, ``/users/me``."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.adapters.user_repo import EmailTaken, UserRepository
from app.domain.refresh_tokens import RefreshTokenError, RefreshTokens
from app.domain.users import (
    RegistrationError,
    User,
    profile,
    validate_display_name,
    validate_email,
    validate_password,
)
from app.security.passwords import hash_password, needs_rehash, verify_password
from app.security.tokens import mint_access_token
from app.settings import Settings
from zeo_common import ApiError
from zeo_common.auth import CurrentPrincipal, JwtSettings

router = APIRouter(prefix="/api/v1", tags=["auth"])

SEED_PLACEHOLDER = "!seed"  # noqa: S105 - marker in infra/postgres/seed/dev-seed.sql, not a secret
# Verified against when the email is unknown, so both paths cost one scrypt (no user probing).
_DUMMY_HASH = hash_password("timing-equaliser-not-a-password")


class RegisterRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)
    display_name: str = Field(max_length=200)


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=200)


class UpdateProfileRequest(BaseModel):
    display_name: str = Field(max_length=200)


class ProfileView(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: str
    kyc_status: str
    suspended: bool
    created_at: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"  # noqa: S105 - the OAuth token type, not a secret
    expires_in: int
    user: ProfileView


def users(request: Request) -> UserRepository:
    return request.app.state.users


def refresh_tokens(request: Request) -> RefreshTokens:
    return request.app.state.refresh_tokens


def jwt_settings(request: Request) -> JwtSettings:
    return request.app.state.jwt_settings


def service_settings(request: Request) -> Settings:
    return request.app.state.settings


Users = Annotated[UserRepository, Depends(users)]
Refresh = Annotated[RefreshTokens, Depends(refresh_tokens)]
Jwt = Annotated[JwtSettings, Depends(jwt_settings)]
Config = Annotated[Settings, Depends(service_settings)]


def invalid_credentials() -> ApiError:
    return ApiError("INVALID_CREDENTIALS", "Email or password is incorrect", 401)


def refresh_error(error: RefreshTokenError) -> ApiError:
    return ApiError(error.code, error.message, 401)


async def token_pair(user: User, jwt: JwtSettings, refresh: str) -> TokenPair:
    return TokenPair(
        access_token=mint_access_token(jwt, user),
        refresh_token=refresh,
        expires_in=jwt.access_ttl_seconds,
        user=ProfileView(**profile(user)),
    )


@router.post("/auth/register", status_code=201, response_model=ProfileView)
async def register(body: RegisterRequest, repo: Users) -> ProfileView:
    try:
        email = validate_email(body.email)
        validate_password(body.password)
        display_name = validate_display_name(body.display_name)
    except RegistrationError as exc:
        raise ApiError("VALIDATION_ERROR", str(exc), 422, {"field": exc.field}) from exc
    now = datetime.now(UTC)
    user = User(
        id=uuid4(), email=email, password_hash=hash_password(body.password),
        display_name=display_name, role="USER", kyc_status="NOT_SUBMITTED", suspended=False,
        token_version=1, created_at=now, updated_at=now,
    )
    try:
        await repo.add(user)
    except EmailTaken as exc:
        raise ApiError(
            "EMAIL_ALREADY_REGISTERED", "An account with this email exists", 409
        ) from exc
    return ProfileView(**profile(user))


async def _check_password(user: User | None, password: str, repo: UserRepository,
                          settings: Settings) -> User:
    if user is None:
        verify_password(password, _DUMMY_HASH)
        raise invalid_credentials()
    if user.password_hash == SEED_PLACEHOLDER:
        if not (settings.accept_seed_password and password == settings.seed_password):
            raise invalid_credentials()
        await repo.set_password_hash(user.id, hash_password(password))
        return user
    if not verify_password(password, user.password_hash):
        raise invalid_credentials()
    if needs_rehash(user.password_hash):
        await repo.set_password_hash(user.id, hash_password(password))
    return user


@router.post("/auth/login", response_model=TokenPair)
async def login(body: LoginRequest, repo: Users, refresh: Refresh, jwt: Jwt,
                settings: Config) -> TokenPair:
    user = await _check_password(await repo.get_by_email(body.email), body.password, repo,
                                 settings)
    return await token_pair(user, jwt, await refresh.issue(user.id))


@router.post("/auth/refresh", response_model=TokenPair)
async def refresh_session(body: RefreshRequest, repo: Users, refresh: Refresh,
                          jwt: Jwt) -> TokenPair:
    try:
        user_id, new_token = await refresh.rotate(body.refresh_token)
    except RefreshTokenError as exc:
        raise refresh_error(exc) from exc
    # Claims are re-read on every refresh, so a role, KYC or suspension change shows up in
    # the next access token (ADR-0005).
    user = await repo.get(user_id)
    if user is None:
        raise refresh_error(RefreshTokenError("REFRESH_TOKEN_INVALID", "Account no longer exists"))
    return await token_pair(user, jwt, new_token)


@router.post("/auth/logout", status_code=204)
async def logout(body: RefreshRequest, refresh: Refresh) -> Response:
    await refresh.revoke(body.refresh_token)
    return Response(status_code=204)


async def _me(repo: UserRepository, principal: CurrentPrincipal) -> User:
    user = await repo.get(principal.user_id)
    if user is None:
        raise ApiError("NOT_FOUND", "Account does not exist", 404)
    return user


@router.get("/users/me", response_model=ProfileView)
async def get_me(repo: Users, principal: CurrentPrincipal) -> ProfileView:
    return ProfileView(**profile(await _me(repo, principal)))


@router.patch("/users/me", response_model=ProfileView)
async def update_me(body: UpdateProfileRequest, repo: Users,
                    principal: CurrentPrincipal) -> ProfileView:
    await _me(repo, principal)
    try:
        display_name = validate_display_name(body.display_name)
    except RegistrationError as exc:
        raise ApiError("VALIDATION_ERROR", str(exc), 422, {"field": exc.field}) from exc
    user = await repo.update_display_name(principal.user_id, display_name)
    return ProfileView(**profile(user))
