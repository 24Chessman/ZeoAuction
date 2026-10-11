"""Password hashing with scrypt (standard library; memory-hard, salted per password).

Stored format: ``scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>``, so the cost can be raised later
and old hashes still verify. Passwords are never logged or returned.
"""

import base64
import hashlib
import hmac
import secrets

N, R, P = 2**14, 8, 1
KEY_LENGTH = 32
SALT_BYTES = 16
SCHEME = "scrypt"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=KEY_LENGTH,
                          maxmem=64 * 1024 * 1024)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _derive(password, salt, N, R, P)
    return f"{SCHEME}${N}${R}${P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check. Unknown formats (for example the seed placeholder) never match."""
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != SCHEME:
            return False
        expected = base64.b64decode(digest)
        actual = _derive(password, base64.b64decode(salt), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def needs_rehash(stored: str) -> bool:
    return not stored.startswith(f"{SCHEME}${N}${R}${P}$")
