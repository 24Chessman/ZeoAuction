"""User accounts: registration rules and the public profile (SDD 7.2, FR-AUTH-1).

Registration collects no KYC documents; sellers verify later through the KYC service
(SDD 8.9). ``role``, ``kyc_status`` and ``suspended`` are never set from a request body.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD, MAX_PASSWORD = 10, 128
MAX_DISPLAY_NAME = 80


@dataclass(frozen=True)
class User:
    id: UUID
    email: str
    password_hash: str
    display_name: str
    role: str
    kyc_status: str
    suspended: bool
    token_version: int
    created_at: datetime
    updated_at: datetime


class RegistrationError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


def normalise_email(email: str) -> str:
    return email.strip().lower()


def validate_email(email: str) -> str:
    email = normalise_email(email)
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise RegistrationError("email", "Enter a valid email address")
    return email


def validate_password(password: str) -> None:
    if not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        raise RegistrationError(
            "password", f"Password must be {MIN_PASSWORD} to {MAX_PASSWORD} characters"
        )
    if password.isalpha() or password.isdigit():
        raise RegistrationError("password", "Password must mix letters with digits or symbols")


def validate_display_name(name: str) -> str:
    name = " ".join(name.split())
    if not 1 <= len(name) <= MAX_DISPLAY_NAME:
        raise RegistrationError(
            "display_name", f"Display name must be 1 to {MAX_DISPLAY_NAME} characters"
        )
    return name


def profile(user: User) -> dict:
    """What ``GET /users/me`` returns. Never the password hash or token version."""
    return {
        "user_id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "kyc_status": user.kyc_status,
        "suspended": user.suspended,
        "created_at": user.created_at.isoformat().replace("+00:00", "Z"),
    }
