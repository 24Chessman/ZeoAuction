from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = REPO_ROOT / "contracts"


@pytest.fixture
def contracts_dir() -> Path:
    return CONTRACTS
