"""config/settlement-policy.yaml and the fee_config seed in the payment schema must agree.

Disclosure, invoice and settlement all read one fee_version (ADR-0011), so the two sources of
the numbers can never drift apart silently.
"""

import re
from decimal import Decimal

import yaml

from .conftest import REPO_ROOT

POLICY_FILE = REPO_ROOT / "config" / "settlement-policy.yaml"
# 60-payment.sql creates the schema; later files (61-payment-razorpay.sql, ...) change the
# active fee. They run in name order, so the last active row inserted is the one in force.
PAYMENT_SQL_FILES = sorted((REPO_ROOT / "infra" / "postgres" / "init").glob("6?-payment*.sql"))

POLICY = yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8"))

FEE_SEED = re.compile(
    r"INSERT INTO payment\.fee_config.*?VALUES\s*"
    r"\('([^']+)',\s*([\d.]+),\s*'([A-Z]{3})',\s*(\d+),\s*true\)",
    re.DOTALL,
)


def seeded_fee_config() -> tuple[str, Decimal, str, int]:
    seeds = [match.groups() for path in PAYMENT_SQL_FILES
             for match in FEE_SEED.finditer(path.read_text(encoding="utf-8"))]
    assert seeds, "no active fee_config seed row in infra/postgres/init/6?-payment*.sql"
    version, fee, currency, window = seeds[-1]
    return version, Decimal(fee), currency, int(window)


def test_superseded_fee_versions_are_deactivated():
    sql = "\n".join(path.read_text(encoding="utf-8") for path in PAYMENT_SQL_FILES)
    versions = [m.group(1) for m in FEE_SEED.finditer(sql)]
    for old in versions[:-1]:
        assert f"SET active = false WHERE fee_version = '{old}'" in sql


def test_checkout_window_is_positive():
    assert POLICY["checkout"]["provider"] == "razorpay"
    assert POLICY["checkout"]["payment_window_hours"] > 0


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
