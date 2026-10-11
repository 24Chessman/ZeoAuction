"""The service raises only codes from contracts/errors (payment + common), at their status."""

import ast
from pathlib import Path

import yaml

from zeo_common.contract_testing import find_contracts_dir

APP = Path(__file__).resolve().parents[1] / "app"


def documented() -> dict[str, int]:
    errors = find_contracts_dir() / "errors"
    codes = {}
    for name in ("payment-error-codes.yaml", "common-error-codes.yaml"):
        for entry in yaml.safe_load((errors / name).read_text(encoding="utf-8"))["codes"]:
            codes[entry["code"]] = entry["http"]
    return codes


def raised() -> set[tuple[str, int]]:
    found = set()
    for path in APP.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "ApiError"
                    and isinstance(node.args[0], ast.Constant)):
                status = node.args[2].value if isinstance(node.args[2], ast.Constant) else None
                found.add((node.args[0].value, status))
    return found


def test_every_raised_code_is_documented_at_its_status():
    codes = documented()
    seen = raised()
    assert seen, "expected ApiError calls in app/"
    for code, status in seen:
        assert code in codes, f"{code} is not in contracts/errors"
        assert status == codes[code], f"{code} raised with {status}, documented {codes[code]}"


def test_every_payment_code_is_used():
    payment = yaml.safe_load((find_contracts_dir() / "errors" / "payment-error-codes.yaml")
                             .read_text(encoding="utf-8"))["codes"]
    used = {code for code, _ in raised()}
    assert {entry["code"] for entry in payment} <= used
