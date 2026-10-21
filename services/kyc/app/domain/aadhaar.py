"""Aadhaar Secure QR, read and verified in memory (UIDAI, "Secure QR Code").

Every Aadhaar letter, e-Aadhaar PDF and PVC card printed since 2019 carries a Secure QR. The
seller uploads a photo of it; ``app/adapters/qr_reader.py`` turns the photo into the QR's
text, and this module does the rest. The text is one big decimal number. As bytes (big
endian) it is a GZip stream; inflated, it reads:

    [V2 0xFF]                      version marker; absent on the first (2019) layout
    indicator 0xFF                 0 none, 1 email, 2 mobile, 3 both registered
    referenceId 0xFF               {last 4 Aadhaar digits}{YYYYMMDDHHMMSSmmm, IST}
    name dob gender careof district landmark house location pincode postoffice
    state street subdistrict vtc   each followed by 0xFF
    [mobile last 4 0xFF]           V2 and later only
    photo                          JPEG 2000
    [email hash] [mobile hash]     first layout only: 32 bytes each, per the indicator
    signature                      256 bytes: RSA-2048 PKCS#1 v1.5 SHA-256 over all before it

Pure logic, no I/O, nothing logs. The signature is checked against the certificates we trust
(UIDAI's, from settings); a QR carries no key of its own. Only :class:`AadhaarSummary` is ever
stored: no Aadhaar number, no address beyond state and PIN code, no QR payload.
"""

import hashlib
import hmac
import re
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from uuid import UUID

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

IST = timezone(timedelta(hours=5, minutes=30))
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_QR_DIGITS = 7089             # the most a QR code (version 40, numeric) can hold
MAX_PAYLOAD_BYTES = 64 * 1024    # inflated; real payloads are a few kilobytes
SIGNATURE_BYTES = 256
HASH_BYTES = 32
DELIMITER = 0xFF
ADULT_AGE = 18
CLOCK_SKEW = timedelta(minutes=5)

# Text fields between the indicator and the photo, in order (first layout and V2 alike).
_FIELDS = ("reference_id", "name", "dob", "gender", "careof", "district", "landmark", "house",
           "location", "pincode", "postoffice", "state", "street", "subdistrict", "vtc")
_VERSION = re.compile(rb"^V(\d)$")
_DIGITS = re.compile(r"^\d+$")
_REFERENCE_ID = re.compile(r"^(\d{4})(\d{14})(\d{3})?$")
_PINCODE = re.compile(r"^\d{6}$")
_GENDERS = {"M": "M", "F": "F", "T": "T", "MALE": "M", "FEMALE": "F", "TRANSGENDER": "T"}
_IMAGE_MAGIC = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")  # JPEG, PNG
_WEBP = (b"RIFF", b"WEBP")
_JP2_MAGIC = (b"\x00\x00\x00\x0cjP  \r\n\x87\n", b"\xff\x4f\xff\x51")  # JP2 box, raw J2K
_JPEG_MAGIC = b"\xff\xd8\xff"
_DIGIT_CHUNK = 1000  # int(str) is capped at 4300 digits, so long numbers go in chunks

# Which form field a reason belongs to, so the page can point at it.
REASON_FIELD = {"mobile_mismatch": "mobile"}


class AadhaarInvalid(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason

    @property
    def field(self) -> str:
        return REASON_FIELD.get(self.reason, "qr_image")


@dataclass(frozen=True)
class TrustedKey:
    """A certificate we accept signatures from, identified by its SHA-256 fingerprint."""

    fingerprint: str
    public_key: rsa.RSAPublicKey


@dataclass(frozen=True)
class SecureQr:
    """What a verified Secure QR says. Held in memory only, never stored as is."""

    version: int                  # 1 for the first layout (no marker), else the marker's digit
    reference_last4: str
    generated_at: datetime
    name: str
    birth_date: date | None
    year_of_birth: int
    gender: str
    state: str | None
    pincode: str | None
    photo: bytes
    signer: str
    mobile_verified: bool | None


@dataclass(frozen=True)
class AadhaarSummary:
    """The row kept in ``kyc.aadhaar_verifications`` (21-kyc-aadhaar.sql)."""

    submission_id: UUID
    reference_last4: str
    qr_generated_at: datetime
    signer_sha256: str
    holder_name: str
    year_of_birth: int
    gender: str
    state: str | None
    pincode: str | None
    mobile_verified: bool | None
    face_model: str
    reference_faces: int
    reference_embedding: tuple[float, ...] | None
    verified_at: datetime


def load_trusted_key(certificate: bytes) -> TrustedKey:
    """A PEM or DER X.509 certificate. Only its RSA public key is used: QR codes printed years
    ago stay valid after the certificate expires, so validity dates are not checked."""
    try:
        cert = (x509.load_pem_x509_certificate(certificate) if b"-----BEGIN" in certificate
                else x509.load_der_x509_certificate(certificate))
    except ValueError as exc:
        raise ValueError("not an X.509 certificate") from exc
    key = cert.public_key()
    if not isinstance(key, rsa.RSAPublicKey):
        raise ValueError("the certificate does not hold an RSA key")
    der = cert.public_bytes(serialization.Encoding.DER)
    return TrustedKey(fingerprint=hashlib.sha256(der).hexdigest(), public_key=key)


def contact_hash(value: str, last_digit: int) -> str:
    """UIDAI's hash of a mobile number or email in the first QR layout: SHA-256 of the value,
    applied as many times as the last Aadhaar digit (once when it is 0 or 1), as hex."""
    digest = value
    for _ in range(max(1, last_digit)):
        digest = hashlib.sha256(digest.encode()).hexdigest()
    return digest


def normalise_mobile(mobile: str) -> str:
    digits = re.sub(r"\D", "", mobile)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) != 10:
        raise AadhaarInvalid("mobile_mismatch", "Enter the 10-digit mobile number")
    return digits


def check_image(data: bytes) -> None:
    """The upload must be a JPEG, PNG or WebP photo within the size limit."""
    if not data:
        raise AadhaarInvalid("not_image", "The file is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise AadhaarInvalid("too_large", "The photo must be at most 8 MB")
    webp = data[:4] == _WEBP[0] and data[8:12] == _WEBP[1]
    if not (data.startswith(_IMAGE_MAGIC) or webp):
        raise AadhaarInvalid("not_image", "Upload a JPEG, PNG or WebP photo of the QR code")


def decimal_to_bytes(text: str) -> bytes:
    """The QR's decimal number as big-endian bytes, without ``int()``'s 4300-digit cap."""
    number = 0
    for start in range(0, len(text), _DIGIT_CHUNK):
        chunk = text[start:start + _DIGIT_CHUNK]
        number = number * 10 ** len(chunk) + int(chunk)
    return number.to_bytes((number.bit_length() + 7) // 8 or 1, "big")


def inflate(text: str) -> bytes:
    """QR text -> the signed payload. Bounded, so a crafted stream can't inflate without end."""
    text = text.strip()
    if not _DIGITS.match(text):
        # The pre-2019 QR held plain, unsigned XML (<PrintLetterBarcodeData .../>).
        raise AadhaarInvalid("not_secure_qr",
                             "This is not an Aadhaar Secure QR code; use a recent Aadhaar")
    if len(text) > MAX_QR_DIGITS:
        raise AadhaarInvalid("malformed_qr", "The QR code could not be read")
    stream = zlib.decompressobj(zlib.MAX_WBITS | 32)  # GZip or zlib header, detected
    try:
        payload = stream.decompress(decimal_to_bytes(text), MAX_PAYLOAD_BYTES + 1)
    except zlib.error as exc:
        raise AadhaarInvalid("not_secure_qr", "This is not an Aadhaar Secure QR code") from exc
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise AadhaarInvalid("malformed_qr", "The QR code holds too much data")
    if not stream.eof:
        raise AadhaarInvalid("malformed_qr", "The QR code is incomplete")
    return payload


def verify_signature(payload: bytes, trusted: Sequence[TrustedKey]) -> TrustedKey:
    """RSA PKCS#1 v1.5 with SHA-256 over everything before the last 256 bytes."""
    if len(payload) <= SIGNATURE_BYTES:
        raise AadhaarInvalid("malformed_qr", "The QR code is incomplete")
    signed, signature = payload[:-SIGNATURE_BYTES], payload[-SIGNATURE_BYTES:]
    for key in trusted:
        try:
            key.public_key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
        except InvalidSignature:
            continue
        return key
    raise AadhaarInvalid("signature_invalid", "The QR code is not signed by UIDAI")


def _text(raw: bytes) -> str:
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError:
        value = raw.decode("latin-1")
    return " ".join(value.split())


@dataclass(frozen=True)
class _Layout:
    version: int
    indicator: int
    fields: dict[str, str]
    mobile_last4: str | None
    photo: bytes
    mobile_hash: bytes | None


def split_payload(signed: bytes) -> _Layout:
    """Cut the signed bytes (signature already removed) into fields, photo and hashes. Only the
    leading delimiters count: the photo and hashes are binary and may contain 0xFF."""
    first = signed.find(DELIMITER)
    marker = _VERSION.match(signed[:first]) if first > 0 else None
    version = int(marker.group(1)) if marker else 1
    count = len(_FIELDS) + 1 + (2 if marker else 0)  # + indicator, + marker and mobile
    parts: list[bytes] = []
    start = 0
    for _ in range(count):
        end = signed.find(DELIMITER, start)
        if end < 0:
            raise AadhaarInvalid("malformed_qr", "The QR code has missing fields")
        parts.append(signed[start:end])
        start = end + 1
    rest = signed[start:]
    if marker:
        parts.pop(0)
    try:
        indicator = int(parts[0])
    except ValueError as exc:
        raise AadhaarInvalid("malformed_qr", "The QR code has missing fields") from exc
    if indicator not in (0, 1, 2, 3):
        raise AadhaarInvalid("malformed_qr", "The QR code has missing fields")
    fields = dict(zip(_FIELDS, (_text(p) for p in parts[1:1 + len(_FIELDS)]), strict=True))

    mobile_last4 = mobile_hash = None
    if marker:
        mobile_last4 = _text(parts[-1]) or None
        photo = rest
    else:
        hashes_len = HASH_BYTES * ((indicator & 1) + (indicator >> 1 & 1))
        if len(rest) < hashes_len:
            raise AadhaarInvalid("no_photo", "The QR code has no photo")
        photo = rest[:len(rest) - hashes_len]
        if indicator & 2:  # the mobile hash comes last, after the email's
            mobile_hash = rest[len(rest) - HASH_BYTES:]
    return _Layout(version, indicator, fields, mobile_last4, photo, mobile_hash)


def parse_reference_id(reference_id: str) -> tuple[str, datetime]:
    """``{last 4 digits}{YYYYMMDDHHMMSS}{mmm}``, the timestamp in IST -> (last4, UTC time)."""
    match = _REFERENCE_ID.match(reference_id or "")
    if match is None:
        raise AadhaarInvalid("malformed_qr", "The QR code has no valid reference id")
    last4, stamp, millis = match.groups()
    try:
        local = datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=IST)
    except ValueError as exc:
        raise AadhaarInvalid("malformed_qr", "The QR code has no valid reference id") from exc
    return last4, (local + timedelta(milliseconds=int(millis or 0))).astimezone(UTC)


def parse_birth(dob: str) -> tuple[date | None, int]:
    """``DD-MM-YYYY`` (the usual form), ``YYYY-MM-DD``, ``DD/MM/YYYY`` or a bare year."""
    value = (dob or "").strip()
    if re.fullmatch(r"\d{4}", value):
        return None, int(value)
    for pattern in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            born = datetime.strptime(value, pattern).date()
        except ValueError:
            continue
        return born, born.year
    raise AadhaarInvalid("malformed_qr", "The QR code has no readable date of birth")


def is_adult(birth_date: date | None, year_of_birth: int, today: date) -> bool:
    """With only a year, assume the latest birthday in it (31 December), so nobody under
    18 passes."""
    born = birth_date or date(year_of_birth, 12, 31)
    try:
        coming_of_age = born.replace(year=born.year + ADULT_AGE)
    except ValueError:  # 29 February
        coming_of_age = date(born.year + ADULT_AGE, 3, 1)
    return coming_of_age <= today


def _check_mobile(layout: _Layout, mobile: str, last_digit: int) -> bool:
    """V2 and later carry the mobile's last four digits; the first layout carries a hash."""
    digits = normalise_mobile(mobile)
    if layout.version >= 2:
        matches = layout.mobile_last4 is not None and hmac.compare_digest(
            digits[-4:], layout.mobile_last4[-4:])
    else:
        matches = layout.mobile_hash is not None and hmac.compare_digest(
            contact_hash(digits, last_digit), layout.mobile_hash.hex())
    if not matches:
        raise AadhaarInvalid(
            "mobile_mismatch", "This mobile number is not the one linked to the Aadhaar"
        )
    return True


def read_payload(
    text: str,
    trusted: Sequence[TrustedKey],
    *,
    now: datetime,
    max_age: timedelta | None,
    mobile: str | None = None,
) -> SecureQr:
    """Verify and read one QR's text; raise :class:`AadhaarInvalid` if any check fails. In
    order: a Secure QR, UIDAI's signature, its layout, the QR's age (when ``max_age`` is
    set), the holder's details, 18 or over, and the mobile number if one was given."""
    payload = inflate(text)
    signer = verify_signature(payload, trusted)
    layout = split_payload(payload[:-SIGNATURE_BYTES])
    fields = layout.fields
    last4, generated_at = parse_reference_id(fields["reference_id"])
    if generated_at > now + CLOCK_SKEW:
        raise AadhaarInvalid("from_future", "The QR code's timestamp is in the future")
    if max_age is not None and now - generated_at > max_age:
        hours = int(max_age.total_seconds() // 3600)
        raise AadhaarInvalid(
            "stale", f"The QR code is older than {hours} hours; download a fresh e-Aadhaar"
        )

    if not fields["name"]:
        raise AadhaarInvalid("malformed_qr", "The QR code has no holder name")
    gender = _GENDERS.get(fields["gender"].upper())
    if gender is None:
        raise AadhaarInvalid("malformed_qr", "The QR code has no valid gender")
    birth_date, year_of_birth = parse_birth(fields["dob"])
    if not is_adult(birth_date, year_of_birth, now.astimezone(IST).date()):
        raise AadhaarInvalid("underage", "Sellers must be 18 or older")
    if not layout.photo.startswith(_JP2_MAGIC + (_JPEG_MAGIC,)):
        raise AadhaarInvalid("no_photo", "The QR code has no readable photo")

    mobile_verified = _check_mobile(layout, mobile, int(last4[-1])) if mobile else None
    pincode = fields["pincode"]
    return SecureQr(
        version=layout.version,
        reference_last4=last4,
        generated_at=generated_at,
        name=fields["name"],
        birth_date=birth_date,
        year_of_birth=year_of_birth,
        gender=gender,
        state=fields["state"] or None,
        pincode=pincode if _PINCODE.match(pincode) else None,
        photo=layout.photo,
        signer=signer.fingerprint,
        mobile_verified=mobile_verified,
    )


def read_secure_qr(
    texts: Sequence[str],
    trusted: Sequence[TrustedKey],
    *,
    now: datetime,
    max_age: timedelta | None,
    mobile: str | None = None,
) -> SecureQr:
    """Pick the Secure QR among the codes found in the photo (an e-Aadhaar page or a card may
    show more than one) and read it. With several candidates, the first that verifies wins;
    otherwise the first one's error is reported."""
    if not texts:
        raise AadhaarInvalid(
            "no_qr", "No QR code was found; photograph it flat, in focus and filling the frame"
        )
    first_error: AadhaarInvalid | None = None
    for text in texts:
        try:
            return read_payload(text, trusted, now=now, max_age=max_age, mobile=mobile)
        except AadhaarInvalid as exc:
            # A real Secure QR's error says more than a stray code's "not a Secure QR".
            if first_error is None or first_error.reason == "not_secure_qr":
                first_error = exc
    raise first_error
