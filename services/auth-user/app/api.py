"""Auth & User Service routes (SDD 7.2): auth, email verification, reset, OTP."""

import logging
import secrets
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.adapters.email_sender import (
    send_otp_email,
    send_password_reset_link_email,
    send_verification_link_email,
)
from app.adapters.user_repo import EmailTaken, UserRepository
from app.domain.email_tokens import InMemoryEmailTokenStore
from app.domain.otp import OtpStore
from app.domain.refresh_tokens import RefreshTokenError, RefreshTokens
from app.domain.users import (
    RegistrationError,
    User,
    profile,
    validate_categories,
    validate_display_name,
    validate_email,
    validate_password,
)
from app.security.passwords import hash_password, needs_rehash, verify_password
from app.security.tokens import mint_access_token
from app.settings import Settings
from zeo_common import ApiError
from zeo_common.auth import CurrentPrincipal, JwtSettings

logger = logging.getLogger("auth_svc.api")

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


class SendGmailOtpRequest(BaseModel):
    email: str = Field(max_length=254)


class SendGmailOtpResponse(BaseModel):
    status: str
    email: str
    expires_in: int
    dev_otp: str | None = None


class VerifyGmailOtpRequest(BaseModel):
    email: str = Field(max_length=254)
    otp: str = Field(min_length=6, max_length=6)
    display_name: str | None = Field(default=None, max_length=200)


class VerifyEmailRequest(BaseModel):
    token: str


class VerifyEmailResponse(BaseModel):
    status: str
    email: str


class ResendVerificationRequest(BaseModel):
    email: str = Field(max_length=254)


class ResendVerificationResponse(BaseModel):
    status: str
    email: str
    dev_verify_link: str | None = None


class ForgotPasswordRequest(BaseModel):
    email: str = Field(max_length=254)


class ForgotPasswordResponse(BaseModel):
    status: str
    email: str
    dev_reset_link: str | None = None


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(max_length=256)


class ResetPasswordResponse(BaseModel):
    status: str
    message: str


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=200)


class UpdateProfileRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    favorite_categories: list[str] | None = None
    onboarded: bool | None = None


class UpdatePreferencesRequest(BaseModel):
    favorite_categories: list[str] = Field(default_factory=list)
    onboarded: bool = True


class ProfileView(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: str
    kyc_status: str
    suspended: bool
    created_at: str
    favorite_categories: list[str] = Field(default_factory=list)
    onboarded: bool = False
    email_verified: bool = False


class RegisterResponse(ProfileView):
    dev_verify_link: str | None = None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"  # noqa: S105 - the OAuth token type, not a secret
    expires_in: int
    user: ProfileView
    is_first_login: bool = False


def users(request: Request) -> UserRepository:
    return request.app.state.users


def refresh_tokens(request: Request) -> RefreshTokens:
    return request.app.state.refresh_tokens


def otp_store(request: Request) -> OtpStore:
    return request.app.state.otp_store


def email_token_store(request: Request) -> InMemoryEmailTokenStore:
    return request.app.state.email_tokens


def jwt_settings(request: Request) -> JwtSettings:
    return request.app.state.jwt_settings


def service_settings(request: Request) -> Settings:
    return request.app.state.settings


Users = Annotated[UserRepository, Depends(users)]
Refresh = Annotated[RefreshTokens, Depends(refresh_tokens)]
Otps = Annotated[OtpStore, Depends(otp_store)]
EmailTokens = Annotated[InMemoryEmailTokenStore, Depends(email_token_store)]
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
        is_first_login=not user.onboarded,
    )


@router.post("/auth/register", status_code=201, response_model=RegisterResponse)
async def register(
    body: RegisterRequest, repo: Users, email_tokens: EmailTokens, settings: Config
) -> RegisterResponse:
    logger.info(
        "[AUTH] Registration attempt for email <%s>, name '%s'", body.email, body.display_name
    )
    try:
        email = validate_email(body.email)
        validate_password(body.password)
        display_name = validate_display_name(body.display_name)
    except RegistrationError as exc:
        logger.warning("[AUTH] Registration validation failed for <%s>: %s", body.email, exc)
        raise ApiError("VALIDATION_ERROR", str(exc), 422, {"field": exc.field}) from exc
    now = datetime.now(UTC)
    user = User(
        id=uuid4(),
        email=email,
        password_hash=hash_password(body.password),
        display_name=display_name,
        role="USER",
        kyc_status="NOT_SUBMITTED",
        suspended=False,
        token_version=1,
        created_at=now,
        updated_at=now,
        favorite_categories=(),
        onboarded=False,
        email_verified=False,
    )
    try:
        await repo.add(user)
    except EmailTaken as exc:
        logger.warning("[AUTH] Registration conflict: email <%s> already registered", email)
        raise ApiError(
            "EMAIL_ALREADY_REGISTERED", "An account with this email exists", 409
        ) from exc

    raw_token, _ = email_tokens.issue(user.id, "VERIFY_EMAIL", ttl_hours=24)
    verify_url = f"{settings.frontend_url}/verify-email?token={raw_token}"
    logger.info(
        "[AUTH] User registered: id=%s, email=<%s>. Sending verification email...",
        user.id,
        email,
    )
    sent = await send_verification_link_email(email, verify_url, settings)
    logger.info("[AUTH] Verification email dispatched to <%s> (sent=%s)", email, sent)

    dev_link = None if sent else verify_url
    return RegisterResponse(**profile(user), dev_verify_link=dev_link)


@router.post("/auth/verify-email", response_model=VerifyEmailResponse)
async def verify_email(
    body: VerifyEmailRequest, repo: Users, email_tokens: EmailTokens
) -> VerifyEmailResponse:
    token_preview = f"{body.token[:8]}..." if len(body.token) >= 8 else body.token
    logger.info("[AUTH] Email verification request received with token %s", token_preview)

    token_record = email_tokens.get_valid(body.token, "VERIFY_EMAIL")
    if not token_record:
        logger.warning("[AUTH-ERROR] Verification failed: token invalid or expired")
        raise ApiError(
            "INVALID_TOKEN", "The verification link is invalid or has expired", 400
        )

    email_tokens.consume(body.token)
    user = await repo.mark_email_verified(token_record.user_id)
    if not user:
        logger.error(
            "[AUTH-ERROR] User id %s not found for verification token",
            token_record.user_id,
        )
        raise ApiError("NOT_FOUND", "Account does not exist", 404)

    logger.info(
        "[AUTH] SUCCESS: User <%s> (id=%s) email verified successfully",
        user.email,
        user.id,
    )
    return VerifyEmailResponse(status="verified", email=user.email)


@router.post("/auth/resend-verification", response_model=ResendVerificationResponse)
async def resend_verification(
    body: ResendVerificationRequest,
    repo: Users,
    email_tokens: EmailTokens,
    settings: Config,
) -> ResendVerificationResponse:
    logger.info("[AUTH] Resend verification requested for <%s>", body.email)
    try:
        email = validate_email(body.email)
    except RegistrationError as exc:
        raise ApiError("VALIDATION_ERROR", str(exc), 422, {"field": exc.field}) from exc

    user = await repo.get_by_email(email)
    dev_link = None
    if user and not user.email_verified:
        raw_token, _ = email_tokens.issue(user.id, "VERIFY_EMAIL", ttl_hours=24)
        verify_url = f"{settings.frontend_url}/verify-email?token={raw_token}"
        sent = await send_verification_link_email(email, verify_url, settings)
        if not sent:
            dev_link = verify_url
        logger.info("[AUTH] Resent verification email to <%s> (sent=%s)", email, sent)
    else:
        logger.info("[AUTH] Resend verification ignored: user not found or already verified")

    return ResendVerificationResponse(
        status="sent", email=email, dev_verify_link=dev_link
    )


@router.post("/auth/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    body: ForgotPasswordRequest,
    repo: Users,
    email_tokens: EmailTokens,
    settings: Config,
) -> ForgotPasswordResponse:
    logger.info("[AUTH-PASSWORD] Forgot password requested for <%s>", body.email)
    try:
        email = validate_email(body.email)
    except RegistrationError as exc:
        raise ApiError("VALIDATION_ERROR", str(exc), 422, {"field": exc.field}) from exc

    user = await repo.get_by_email(email)
    dev_link = None
    if user:
        raw_token, _ = email_tokens.issue(user.id, "RESET_PASSWORD", ttl_hours=1)
        reset_url = f"{settings.frontend_url}/reset-password?token={raw_token}"
        sent = await send_password_reset_link_email(email, reset_url, settings)
        if not sent:
            dev_link = reset_url
        logger.info(
            "[AUTH-PASSWORD] Password reset email dispatched to <%s> (sent=%s)",
            email,
            sent,
        )
    else:
        logger.info(
            "[AUTH-PASSWORD] Forgot password requested for unknown email <%s> (ignored)",
            email,
        )

    return ForgotPasswordResponse(
        status="sent", email=email, dev_reset_link=dev_link
    )


@router.post("/auth/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    body: ResetPasswordRequest,
    repo: Users,
    email_tokens: EmailTokens,
) -> ResetPasswordResponse:
    token_preview = f"{body.token[:8]}..." if len(body.token) >= 8 else body.token
    logger.info("[AUTH-PASSWORD] Reset password attempt with token %s", token_preview)
    try:
        validate_password(body.new_password)
    except RegistrationError as exc:
        raise ApiError("VALIDATION_ERROR", str(exc), 422, {"field": exc.field}) from exc

    token_record = email_tokens.get_valid(body.token, "RESET_PASSWORD")
    if not token_record:
        logger.warning("[AUTH-PASSWORD-ERROR] Reset link invalid or expired")
        raise ApiError(
            "INVALID_TOKEN", "The reset link is invalid or has expired", 400
        )

    await repo.set_password_hash(
        token_record.user_id, hash_password(body.new_password)
    )
    email_tokens.consume(body.token)
    logger.info("[AUTH-PASSWORD] SUCCESS: Password updated for user_id=%s", token_record.user_id)

    return ResetPasswordResponse(
        status="password_updated", message="Password updated successfully"
    )


async def _check_password(
    user: User | None, password: str, repo: UserRepository, settings: Settings
) -> User:
    if user is None:
        verify_password(password, _DUMMY_HASH)
        logger.warning("[AUTH-ERROR] Login failed: unknown user email")
        raise invalid_credentials()
    if user.password_hash == SEED_PLACEHOLDER:
        if not (settings.accept_seed_password and password == settings.seed_password):
            logger.warning(
                "[AUTH-ERROR] Login failed: incorrect seed password for <%s>", user.email
            )
            raise invalid_credentials()
        await repo.set_password_hash(user.id, hash_password(password))
        if not user.email_verified:
            user = await repo.mark_email_verified(user.id) or user
        return user
    if not verify_password(password, user.password_hash):
        logger.warning("[AUTH-ERROR] Login failed: incorrect password for <%s>", user.email)
        raise invalid_credentials()
    if needs_rehash(user.password_hash):
        await repo.set_password_hash(user.id, hash_password(password))
    return user


@router.post("/auth/login", response_model=TokenPair)
async def login(
    body: LoginRequest, repo: Users, refresh: Refresh, jwt: Jwt, settings: Config
) -> TokenPair:
    logger.info("[AUTH] Login attempt for email <%s>", body.email)
    user = await _check_password(
        await repo.get_by_email(body.email), body.password, repo, settings
    )
    if not user.email_verified:
        logger.warning("[AUTH-BLOCKED] Login rejected for <%s>: email not verified", user.email)
        raise ApiError(
            "EMAIL_NOT_VERIFIED",
            "Please verify your email address before logging in. "
            "Check your inbox for the verification link.",
            403,
            {"email": user.email},
        )
    logger.info(
        "[AUTH] Login SUCCESS for user <%s> (id=%s, role=%s, kyc=%s)",
        user.email,
        user.id,
        user.role,
        user.kyc_status,
    )
    return await token_pair(user, jwt, await refresh.issue(user.id))


@router.post("/auth/gmail/send-otp", response_model=SendGmailOtpResponse)
async def send_gmail_otp(
    body: SendGmailOtpRequest, otps: Otps, settings: Config
) -> SendGmailOtpResponse:
    logger.info("[AUTH-OTP] Requesting OTP code for <%s>", body.email)
    try:
        email = validate_email(body.email)
    except RegistrationError as exc:
        raise ApiError("VALIDATION_ERROR", str(exc), 422, {"field": exc.field}) from exc

    record = otps.issue(email)
    sent = await send_otp_email(email, record.code, settings)
    dev_otp = None if sent else record.code
    logger.info("[AUTH-OTP] OTP code issued and email dispatched to <%s> (sent=%s)", email, sent)
    return SendGmailOtpResponse(
        status="sent",
        email=email,
        expires_in=600,
        dev_otp=dev_otp,
    )


@router.post("/auth/gmail/verify-otp", response_model=TokenPair)
async def verify_gmail_otp(
    body: VerifyGmailOtpRequest, repo: Users, refresh: Refresh, otps: Otps, jwt: Jwt
) -> TokenPair:
    logger.info("[AUTH-OTP] Verifying OTP code for <%s>", body.email)
    try:
        email = validate_email(body.email)
    except RegistrationError as exc:
        raise ApiError("VALIDATION_ERROR", str(exc), 422, {"field": exc.field}) from exc

    valid = otps.verify(email, body.otp)
    if not valid:
        logger.warning("[AUTH-OTP-ERROR] Invalid or expired OTP for <%s>", email)
        raise ApiError("INVALID_OTP", "The verification code is incorrect or expired", 401)

    user = await repo.get_by_email(email)
    if user is None:
        now = datetime.now(UTC)
        display_name = body.display_name.strip() if body.display_name else email.split("@")[0]
        if not display_name:
            display_name = "User"
        display_name = display_name[:80]
        random_pw = secrets.token_urlsafe(32)
        user = User(
            id=uuid4(),
            email=email,
            password_hash=hash_password(random_pw),
            display_name=display_name,
            role="USER",
            kyc_status="NOT_SUBMITTED",
            suspended=False,
            token_version=1,
            created_at=now,
            updated_at=now,
            favorite_categories=(),
            onboarded=False,
            email_verified=True,  # Verified directly by proving access to Gmail
        )
        try:
            await repo.add(user)
            logger.info("[AUTH-OTP] New user created via Gmail OTP: <%s> (id=%s)", email, user.id)
        except EmailTaken:
            # Race condition: reload user
            user = await repo.get_by_email(email)

    if user is None:
        logger.error("[AUTH-OTP-ERROR] Account could not be created for <%s>", email)
        raise ApiError("NOT_FOUND", "Account could not be created", 500)

    if not user.email_verified:
        user = await repo.mark_email_verified(user.id) or user

    logger.info("[AUTH-OTP] SUCCESS: OTP login succeeded for <%s> (id=%s)", email, user.id)
    return await token_pair(user, jwt, await refresh.issue(user.id))


@router.post("/auth/refresh", response_model=TokenPair)
async def refresh_session(
    body: RefreshRequest, repo: Users, refresh: Refresh, jwt: Jwt
) -> TokenPair:
    try:
        user_id, new_token = await refresh.rotate(body.refresh_token)
    except RefreshTokenError as exc:
        raise refresh_error(exc) from exc
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
async def update_me(
    body: UpdateProfileRequest, repo: Users, principal: CurrentPrincipal
) -> ProfileView:
    user = await _me(repo, principal)
    if body.display_name is not None:
        try:
            display_name = validate_display_name(body.display_name)
        except RegistrationError as exc:
            raise ApiError("VALIDATION_ERROR", str(exc), 422, {"field": exc.field}) from exc
        user = await repo.update_display_name(principal.user_id, display_name)
    if body.favorite_categories is not None or body.onboarded is not None:
        categories = (
            validate_categories(body.favorite_categories)
            if body.favorite_categories is not None
            else list(user.favorite_categories)
        )
        onboarded = body.onboarded if body.onboarded is not None else user.onboarded
        user = await repo.update_preferences(principal.user_id, categories, onboarded)
    return ProfileView(**profile(user))


@router.put("/users/me/preferences", response_model=ProfileView)
async def update_user_preferences(
    body: UpdatePreferencesRequest, repo: Users, principal: CurrentPrincipal
) -> ProfileView:
    await _me(repo, principal)
    valid_categories = validate_categories(body.favorite_categories)
    updated = await repo.update_preferences(principal.user_id, valid_categories, body.onboarded)
    if updated is None:
        raise ApiError("NOT_FOUND", "Account does not exist", 404)
    return ProfileView(**profile(updated))
