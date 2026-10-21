"""Build a synthetic Aadhaar Secure QR, signed with a dev certificate.

A real Secure QR is signed by UIDAI and holds a real person's data, so tests and demos use
this instead: the same byte layout (V2 by default, or the first 2019 layout with mobile and
email hashes), the same RSA-2048 SHA-256 signature, the same GZip and decimal encoding, but
signed by a key generated here. The KYC service only accepts it when the dev certificate is
added with ``KYC_EXTRA_TRUSTED_CERTS``; never do that in a hosted environment.

    python services/kyc/scripts/synthetic_qr.py --photo me.jpg --name "Asha Verma" \\
        --dob 14-02-1998 --gender F --mobile 9876543210 --out asha-qr.png

Upload the PNG (or a phone photo of it on screen) on the KYC page. The dev key and certificate
are created once in ``services/kyc/dev-certs/`` (git-ignored).
"""

import argparse
import gzip
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

IST = timezone(timedelta(hours=5, minutes=30))
DEV_CERTS = Path(__file__).resolve().parent.parent / "dev-certs"
SEP = b"\xff"


@dataclass(frozen=True)
class SigningIdentity:
    key: rsa.RSAPrivateKey
    certificate: bytes  # PEM


@dataclass(frozen=True)
class Holder:
    name: str = "Asha Verma"
    dob: str = "14-02-1998"
    gender: str = "F"
    aadhaar_last4: str = "3632"
    state: str = "Maharashtra"
    district: str = "Pune"
    pincode: str = "411001"
    mobile: str | None = "9876543210"
    email: str | None = None


def make_identity(common_name: str = "zeoauction-dev-secure-qr") -> SigningIdentity:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    return SigningIdentity(key=key, certificate=cert.public_bytes(serialization.Encoding.PEM))


def load_or_create_identity(directory: Path = DEV_CERTS) -> SigningIdentity:
    key_path, cert_path = directory / "dev-secure-qr.key", directory / "dev-secure-qr.cer"
    if key_path.is_file() and cert_path.is_file():
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        return SigningIdentity(key=key, certificate=cert_path.read_bytes())
    identity = make_identity()
    directory.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(identity.key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    cert_path.write_bytes(identity.certificate)
    return identity


def contact_hash(value: str, last_digit: int) -> str:
    digest = value
    for _ in range(max(1, last_digit)):
        digest = hashlib.sha256(digest.encode()).hexdigest()
    return digest


def bytes_to_decimal(data: bytes) -> str:
    """Big-endian bytes as a decimal number, in chunks (``str(int)`` stops at 4300 digits)."""
    number, base, chunks = int.from_bytes(data, "big"), 10 ** 1000, []
    while number >= base:
        number, low = divmod(number, base)
        chunks.append(f"{low:01000d}")
    return str(number) + "".join(reversed(chunks))


def reference_id(last4: str, generated_at: datetime) -> str:
    local = generated_at.astimezone(IST)
    return f"{last4}{local:%Y%m%d%H%M%S}{local.microsecond // 1000:03d}"


def build_payload(holder: Holder, photo: bytes, generated_at: datetime, *,
                  version: int = 2) -> bytes:
    """The signed part: fields, photo and (first layout only) contact hashes."""
    indicator = (1 if holder.email else 0) + (2 if holder.mobile else 0)
    fields = [
        str(indicator), reference_id(holder.aadhaar_last4, generated_at), holder.name,
        holder.dob, holder.gender, "", holder.district, "", "12", "Shivajinagar",
        holder.pincode, "Pune City", holder.state, "FC Road", "Pune City", "Pune",
    ]
    if version >= 2:
        fields = [f"V{version}", *fields, (holder.mobile or "")[-4:]]
        return SEP.join(f.encode() for f in fields) + SEP + photo
    last_digit = int(holder.aadhaar_last4[-1])
    hashes_ = b"".join(bytes.fromhex(contact_hash(value, last_digit))
                       for value in (holder.email, holder.mobile) if value)
    return SEP.join(f.encode() for f in fields) + SEP + photo + hashes_


def sign(signed: bytes, identity: SigningIdentity) -> bytes:
    """RSA PKCS#1 v1.5 with SHA-256, appended (256 bytes for a 2048-bit key)."""
    return signed + identity.key.sign(signed, padding.PKCS1v15(), hashes.SHA256())


def encode(payload: bytes) -> str:
    """GZip, then the bytes as one decimal number: what the QR code holds."""
    return bytes_to_decimal(gzip.compress(payload, mtime=0))


def make_qr_text(identity: SigningIdentity, photo: bytes, *, holder: Holder | None = None,
                 generated_at: datetime | None = None, version: int = 2) -> str:
    """A complete, valid Secure QR text: build, sign, compress, encode."""
    signed = build_payload(holder or Holder(), photo, generated_at or datetime.now(UTC),
                           version=version)
    return encode(sign(signed, identity))


def qr_png(text: str, *, scale: int = 4) -> bytes:
    """The text as a QR code image (PNG), as a seller would photograph it."""
    import cv2
    import numpy as np
    import zxingcpp

    barcode = zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.QRCode, ec_level="M")
    image = np.array(zxingcpp.write_barcode_to_image(barcode, scale=scale))
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise SystemExit("could not encode the QR image")
    return buffer.tobytes()


def to_jpeg2000(image_bytes: bytes, width: int = 60) -> bytes:
    """Shrink a photo to roughly what UIDAI puts in the QR and encode it as JPEG 2000."""
    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise SystemExit("could not read the photo")
    height = round(image.shape[0] * width / image.shape[1])
    small = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".jp2", small, [cv2.IMWRITE_JPEG2000_COMPRESSION_X1000, 100])
    if not ok:
        raise SystemExit("could not encode JPEG 2000")
    return buffer.tobytes()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--photo", type=Path, required=True, help="a JPEG or PNG of the face")
    parser.add_argument("--name", default=Holder.name)
    parser.add_argument("--dob", default=Holder.dob, help="DD-MM-YYYY")
    parser.add_argument("--gender", default=Holder.gender, choices=["M", "F", "T"])
    parser.add_argument("--last4", default=Holder.aadhaar_last4)
    parser.add_argument("--mobile", default=Holder.mobile)
    parser.add_argument("--layout", type=int, default=2, choices=[1, 2],
                        help="2 = V2 (current), 1 = the first 2019 layout")
    parser.add_argument("--out", type=Path, required=True, help="the QR image (.png)")
    args = parser.parse_args()

    identity = load_or_create_identity()
    holder = Holder(name=args.name, dob=args.dob, gender=args.gender,
                    aadhaar_last4=args.last4, mobile=args.mobile)
    text = make_qr_text(identity, to_jpeg2000(args.photo.read_bytes()), holder=holder,
                        version=args.layout)
    args.out.write_bytes(qr_png(text))
    print(f"wrote {args.out} ({len(text)} digits)")
    print(f"trust it in dev with KYC_EXTRA_TRUSTED_CERTS={DEV_CERTS / 'dev-secure-qr.cer'}")


if __name__ == "__main__":
    main()
