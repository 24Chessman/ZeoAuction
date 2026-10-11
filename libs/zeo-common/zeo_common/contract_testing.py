"""Test helper: validate payloads against the published contracts in ``contracts/``.

Services use this in their unit tests so a response, a fake or an event that drifts from the
frozen contract fails CI (contracts/README.md, rule 5). It resolves ``$ref`` across the
OpenAPI files (``common.v1.yaml#/...``) and returns a plain JSON Schema (OpenAPI 3.1 schemas
are JSON Schema 2020-12). ``pyyaml`` and ``jsonschema`` come from requirements-dev.txt; they
are imported lazily so service images never need them.
"""

import json
from functools import cache
from pathlib import Path
from typing import Any


def find_contracts_dir() -> Path:
    """Walk up to the repository's ``contracts/``, from the working directory (a test run
    inside ``services/<name>``) and then from this file (an editable install)."""
    for start in (Path.cwd().resolve(), Path(__file__).resolve()):
        for parent in [start, *start.parents]:
            candidate = parent / "contracts"
            if (candidate / "README.md").is_file():
                return candidate
    raise FileNotFoundError("contracts/ not found above " + str(Path.cwd()))


@cache
def _load(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    import yaml

    return yaml.safe_load(text)


def _pointer(document: Any, pointer: str) -> Any:
    node = document
    for part in pointer.lstrip("/").split("/"):
        if part:
            node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def _inline(node: Any, path: Path) -> Any:
    if isinstance(node, list):
        return [_inline(item, path) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        target, _, pointer = node["$ref"].partition("#")
        target_path = (path.parent / target).resolve() if target else path
        resolved = _inline(_pointer(_load(target_path), pointer), target_path)
        siblings = {k: _inline(v, path) for k, v in node.items() if k != "$ref"}
        return {**resolved, **siblings} if isinstance(resolved, dict) else resolved
    return {key: _inline(value, path) for key, value in node.items()}


def contract_schema(relative_path: str, pointer: str = "") -> dict[str, Any]:
    """Schema at ``pointer`` inside ``contracts/<relative_path>``, with every ``$ref`` inlined.

    Example: ``contract_schema("openapi/internal/auction-state.v1.yaml",
    "/components/schemas/AuctionState")``.
    """
    path = (find_contracts_dir() / relative_path).resolve()
    return _inline(_pointer(_load(path), pointer), path)


def assert_matches_contract(payload: Any, relative_path: str, pointer: str = "") -> None:
    """Raise ``jsonschema.ValidationError`` if ``payload`` breaks the contract schema."""
    from jsonschema import Draft202012Validator, FormatChecker

    schema = contract_schema(relative_path, pointer)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
