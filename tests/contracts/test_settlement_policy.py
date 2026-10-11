"""config/settlement-policy.yaml and the fee_config seed in the payment schema must agree.

Disclosure, invoice and settlement all read one fee_version (ADR-0011), so the two sources of
the numbers can never drift apart silently.
"""

import re
from decimal import Decimal

import yaml

from .conftest import REPO_ROOT

POLICY_FILE = REPO_ROOT / "config" / "settlement-policy.yaml"
PAYMENT_SQL_FILE = REPO_ROOT / "infra" / "postgres" / "init" / "60-payment.sql"

POLICY = yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8"))
PAYMENT_SQL = PAYMENT_SQL_FILE.read_text(encoding="utf-8")

FEE_SEED = re.compile(
    r"INSERT INTO payment\.fee_config.*?VALUES\s*"
    r"\('([^']+)',\s*([\d.]+),\s*'([A-Z]{3})',\s*(\d+),\s*true\)",
    re.DOTALL,
)


def seeded_fee_config() -> tuple[str, Decimal, str, int]:
    match = FEE_SEED.search(PAYMENT_SQL)
    assert match, "fee_config seed row not found in 60-payment.sql"
    version, fee, currency, window = match.groups()
    return version, Decimal(fee), currency, int(window)


def test_fee_config_seed_matches_policy():
    version, fee, currency, window = seeded_fee_config()
    fee_policy = POLICY["convenience_fee"]
    assert version == fee_policy["fee_version"]
    assert fee == Decimal(fee_policy["amount"])
    assert currency == fee_policy["currency"]
    assert window == POLICY["protection_window"]["days"]


def test_fee_is_a_decimal_string_not_a_float():
    assert isinstance(POLICY["convenience_fee"]["amount"], str)
    assert re.fullmatch(r"\d+\.\d{2}", POLICY["convenience_fee"]["amount"])


def test_refund_fee_treatment_covers_every_fault():
    treatment = POLICY["refund_fee_treatment"]
    assert treatment == {"BUYER": "RETAIN_FEE", "SELLER": "REFUND_FEE", "PLATFORM": "REFUND_FEE"}


def test_anti_snipe_values_are_positive():
    anti_snipe = POLICY["anti_snipe"]
    assert anti_snipe["guard_interval_seconds"] > 0
    assert anti_snipe["extension_seconds"] > 0
    assert anti_snipe["max_extensions"] >= 0
