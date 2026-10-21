"""The Secure QR reader against synthetic QR codes signed like UIDAI's (scripts/)."""

import gzip
import hashlib
from datetime import UTC, date, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.adapters.qr_reader import ZxingQrReader
from app.domain.aadhaar import (
    MAX_IMAGE_BYTES,
    MAX_QR_DIGITS,
    AadhaarInvalid,
    check_image,
    contact_hash,
    decimal_to_bytes,
    inflate,
    is_adult,
    load_trusted_key,
    normalise_mobile,
    parse_birth,
    parse_reference_id,
    read_secure_qr,
)
from app.settings import UIDAI_CERTIFICATE
from scripts.synthetic_qr import (
    Holder,
    build_payload,
    bytes_to_decimal,
    encode,
    make_identity,
    qr_png,
    sign,
)
from tests.support import IDENTITY, JP2, JPEG, PNG, TRUSTED, qr_text

NOW = datetime(2026, 10, 20, 9, 30, tzinfo=UTC)


def read(text: str | list[str], **kwargs):
    kwargs.setdefault("now", NOW)
    kwargs.setdefault("max_age", None)
    return read_secure_qr([text] if isinstance(text, str) else text, [TRUSTED], **kwargs)


def reason(text: str | list[str], **kwargs) -> str:
    with pytest.raises(AadhaarInvalid) as caught:
        read(text, **kwargs)
    return caught.value.reason


def qr(holder: Holder | None = None, *, at: datetime = NOW, **kwargs) -> str:
    return qr_text(holder, generated_at=at, **kwargs)


def signed_text(signed: bytes) -> str:
    """Sign and encode hand-built bytes, to test layouts the generator doesn't make."""
    return encode(sign(signed, IDENTITY))


# ------------------------------------------------------------------ the happy path


@pytest.mark.parametrize("version", [2, 1])
def test_a_valid_qr_is_read_with_only_what_we_need(version):
    result = read(qr(at=NOW - timedelta(days=400), version=version), mobile="+91 98765 43210")
    assert result.version == version
    assert result.name == "Asha Verma"
    assert (result.birth_date, result.year_of_birth) == (date(1998, 2, 14), 1998)
    assert (result.gender, result.reference_last4) == ("F", "3632")
    assert (result.state, result.pincode) == ("Maharashtra", "411001")
    assert result.photo == JP2
    assert result.signer == TRUSTED.fingerprint
    assert result.mobile_verified is True
    assert result.generated_at == NOW - timedelta(days=400)


def test_without_a_mobile_number_the_mobile_is_not_checked():
    assert read(qr()).mobile_verified is None


def test_names_are_whitespace_normalised():
    assert read(qr(Holder(name="  Asha   Verma "))).name == "Asha Verma"


def test_the_photo_may_contain_the_delimiter_byte():
    photo = JP2 + b"\xff\xff\x00\xff"
    assert read(qr(photo=photo)).photo == photo
    assert read(qr(photo=photo, version=1)).photo == photo


def test_full_word_genders_are_accepted():
    assert read(qr(Holder(gender="Male"))).gender == "M"


# ------------------------------------------------------------------ the image and the code


@pytest.mark.parametrize("data", [b"", b"%PDF-1.7", b"GIF89a", b"RIFF1234WAVE"])
def test_non_images_are_refused(data):
    with pytest.raises(AadhaarInvalid) as caught:
        check_image(data)
    assert (caught.value.reason, caught.value.field) == ("not_image", "qr_image")


def test_jpeg_png_and_webp_are_accepted():
    for data in (JPEG, PNG, b"RIFF\x00\x00\x00\x00WEBPVP8 "):
        check_image(data)


def test_oversized_images_are_refused():
    with pytest.raises(AadhaarInvalid) as caught:
        check_image(JPEG + b"\x00" * MAX_IMAGE_BYTES)
    assert caught.value.reason == "too_large"


def test_a_photo_without_a_qr_code_says_so():
    assert reason([]) == "no_qr"


def test_the_old_unsigned_xml_qr_is_refused():
    old = '<?xml version="1.0"?><PrintLetterBarcodeData uid="xxxx" name="Asha"/>'
    assert reason(old) == "not_secure_qr"


def test_a_number_that_is_not_gzip_is_not_a_secure_qr():
    assert reason("1234567890" * 20) == "not_secure_qr"


def test_an_overlong_number_is_refused_before_converting():
    assert reason("1" * (MAX_QR_DIGITS + 1)) == "malformed_qr"


def test_a_truncated_stream_is_refused():
    data = decimal_to_bytes(qr())
    assert reason(bytes_to_decimal(data[: len(data) // 2])) == "malformed_qr"


def test_a_compression_bomb_is_cut_off():
    bomb = bytes_to_decimal(gzip.compress(b"\x00" * (1024 * 1024)))
    with pytest.raises(AadhaarInvalid) as caught:
        inflate(bomb)
    assert caught.value.reason == "malformed_qr"


def test_among_several_codes_the_secure_qr_is_picked():
    assert read(["https://example.com/menu", qr()]).name == "Asha Verma"


def test_among_several_codes_the_real_error_is_reported():
    young = qr(Holder(dob="01-01-2015"))
    assert reason(["https://example.com/menu", young]) == "underage"


def test_decimal_conversion_round_trips_past_the_int_digit_cap():
    data = bytes(range(1, 256)) * 12  # ~7400 digits, beyond int()'s default 4300
    assert decimal_to_bytes(bytes_to_decimal(data)) == data


# ------------------------------------------------------------------ the signature


def test_any_change_after_signing_breaks_the_signature():
    payload = sign(build_payload(Holder(), JP2, NOW), IDENTITY)
    tampered = payload.replace(b"Asha Verma", b"Eve Mallory")
    assert reason(encode(tampered)) == "signature_invalid"


def test_a_signature_by_an_untrusted_key_is_refused():
    assert reason(qr(identity=make_identity("someone-else"))) == "signature_invalid"


def test_a_payload_too_short_to_hold_a_signature_is_malformed():
    assert reason(encode(b"V2\xff0\xff")) == "malformed_qr"


def test_the_bundled_uidai_certificate_loads_and_rejects_dev_signatures():
    uidai = load_trusted_key(UIDAI_CERTIFICATE.read_bytes())
    assert len(uidai.fingerprint) == 64
    with pytest.raises(AadhaarInvalid) as caught:
        read_secure_qr([qr()], [uidai], now=NOW, max_age=None)
    assert caught.value.reason == "signature_invalid"


def test_der_certificates_load_too():
    der = x509.load_pem_x509_certificate(IDENTITY.certificate).public_bytes(
        serialization.Encoding.DER)
    assert load_trusted_key(der).fingerprint == TRUSTED.fingerprint


def test_only_rsa_certificates_are_accepted():
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ec")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(1)
            .not_valid_before(NOW).not_valid_after(NOW + timedelta(days=1))
            .sign(key, hashes.SHA256()))
    with pytest.raises(ValueError):
        load_trusted_key(cert.public_bytes(serialization.Encoding.PEM))
    with pytest.raises(ValueError):
        load_trusted_key(b"not a certificate")


# ------------------------------------------------------------------ the layout


def test_missing_fields_are_malformed():
    assert reason(signed_text(b"V2\xff3\xff363220261020093000000\xffAsha")) == "malformed_qr"


def test_an_unknown_indicator_is_malformed():
    signed = build_payload(Holder(), JP2, NOW).replace(b"V2\xff2\xff", b"V2\xff7\xff", 1)
    assert reason(signed_text(signed)) == "malformed_qr"


def test_first_layout_hashes_must_fit_before_the_signature():
    signed = build_payload(Holder(email="a@b.in"), b"", NOW, version=1)
    assert reason(signed_text(signed[:-40])) == "no_photo"


# ------------------------------------------------------------------ freshness and holder


def test_no_age_limit_by_default_but_one_can_be_set():
    old = qr(at=NOW - timedelta(days=3 * 365))
    assert read(old).name == "Asha Verma"
    assert reason(old, max_age=timedelta(hours=72)) == "stale"
    assert read(qr(at=NOW - timedelta(hours=71)), max_age=timedelta(hours=72))


def test_a_qr_from_the_future_is_refused():
    assert reason(qr(at=NOW + timedelta(hours=1))) == "from_future"


def test_sellers_must_be_adults():
    assert reason(qr(Holder(dob="21-10-2008"))) == "underage"
    assert read(qr(Holder(dob="20-10-2008"))).year_of_birth == 2008


@pytest.mark.parametrize("gender", ["X", ""])
def test_an_invalid_gender_is_refused(gender):
    assert reason(qr(Holder(gender=gender))) == "malformed_qr"


def test_a_missing_photo_is_refused():
    assert reason(qr(photo=b"")) == "no_photo"
    assert reason(qr(photo=b"GIF89a")) == "no_photo"


def test_a_missing_name_is_refused():
    assert reason(qr(Holder(name=" "))) == "malformed_qr"


def test_an_invalid_pincode_is_dropped_not_fatal():
    assert read(qr(Holder(pincode="41100"))).pincode is None


# ------------------------------------------------------------------ the mobile check


def test_contact_hash_follows_uidai_rule():
    # SHA-256 applied "last Aadhaar digit" times, once for 0 and 1.
    once = hashlib.sha256(b"1234567890").hexdigest()
    twice = hashlib.sha256(once.encode()).hexdigest()
    assert contact_hash("1234567890", 2) == twice
    assert contact_hash("1234567890", 0) == once
    assert contact_hash("1234567890", 1) == once


@pytest.mark.parametrize("version", [2, 1])
def test_a_different_mobile_is_a_mismatch_on_its_field(version):
    with pytest.raises(AadhaarInvalid) as caught:
        read(qr(version=version), mobile="9999999999")
    assert (caught.value.reason, caught.value.field) == ("mobile_mismatch", "mobile")


def test_v2_compares_the_last_four_digits_only():
    assert read(qr(), mobile="9000003210").mobile_verified is True


def test_first_layout_finds_the_mobile_hash_after_the_email_hash():
    holder = Holder(email="asha@example.in")
    assert read(qr(holder, version=1), mobile="9876543210").mobile_verified is True


@pytest.mark.parametrize("version", [2, 1])
def test_a_mobile_cannot_be_checked_when_none_is_linked(version):
    assert reason(qr(Holder(mobile=None), version=version), mobile="9876543210") == (
        "mobile_mismatch")


@pytest.mark.parametrize(("raw", "expected"),
                         [("9876543210", "9876543210"), ("+91 98765-43210", "9876543210"),
                          ("919876543210", "9876543210")])
def test_mobile_numbers_are_normalised(raw, expected):
    assert normalise_mobile(raw) == expected


def test_a_short_mobile_is_refused():
    with pytest.raises(AadhaarInvalid):
        normalise_mobile("12345")


# ------------------------------------------------------------------ small parsers


def test_reference_ids_carry_the_last_four_digits_and_ist_time():
    last4, at = parse_reference_id("363220181001134543123")
    assert last4 == "3632"
    assert at == datetime(2018, 10, 1, 8, 15, 43, 123000, tzinfo=UTC)  # 13:45:43 IST
    assert parse_reference_id("363220181001134543")[0] == "3632"  # no milliseconds
    for bad in ("", "abc", "3632201813011345431"):
        with pytest.raises(AadhaarInvalid):
            parse_reference_id(bad)


@pytest.mark.parametrize(
    ("dob", "expected"),
    [("14-02-1998", (date(1998, 2, 14), 1998)), ("1998-02-14", (date(1998, 2, 14), 1998)),
     ("14/02/1998", (date(1998, 2, 14), 1998)), ("1998", (None, 1998))],
)
def test_birth_formats(dob, expected):
    assert parse_birth(dob) == expected


def test_an_unreadable_birth_date_is_refused():
    with pytest.raises(AadhaarInvalid):
        parse_birth("yesterday")


def test_adulthood_with_only_a_year_assumes_the_latest_birthday():
    assert not is_adult(None, 2008, date(2026, 12, 30))
    assert is_adult(None, 2008, date(2026, 12, 31))
    assert is_adult(date(2008, 2, 29), 2008, date(2026, 3, 1))
    assert not is_adult(date(2008, 2, 29), 2008, date(2026, 2, 28))


# ------------------------------------------------------------------ the zxing-cpp reader


def test_the_reader_decodes_a_qr_photo():
    import cv2
    import numpy as np

    text = qr()
    image = cv2.imdecode(np.frombuffer(qr_png(text, scale=6), np.uint8), cv2.IMREAD_GRAYSCALE)
    turn = cv2.getRotationMatrix2D((image.shape[1] / 2, image.shape[0] / 2), 12, 0.9)
    photo = cv2.GaussianBlur(cv2.warpAffine(image, turn, image.shape[::-1], borderValue=255),
                             (3, 3), 0)
    ok, jpeg = cv2.imencode(".jpg", photo, [cv2.IMWRITE_JPEG_QUALITY, 80])
    assert ok
    assert ZxingQrReader().read(jpeg.tobytes()) == [text]


def test_the_reader_scales_down_huge_photos():
    import cv2
    import numpy as np

    text = qr()
    image = cv2.imdecode(np.frombuffer(qr_png(text, scale=4), np.uint8), cv2.IMREAD_GRAYSCALE)
    big = cv2.copyMakeBorder(image, 2200, 2200, 2200, 2200, cv2.BORDER_CONSTANT, value=255)
    ok, png = cv2.imencode(".png", big)
    assert ok
    assert ZxingQrReader().read(png.tobytes()) == [text]


def test_the_reader_finds_nothing_in_a_blank_image_and_none_in_garbage():
    import cv2
    import numpy as np

    ok, blank = cv2.imencode(".png", np.full((200, 200), 255, np.uint8))
    assert ZxingQrReader().read(blank.tobytes()) == []
    assert ZxingQrReader().read(PNG) is None
