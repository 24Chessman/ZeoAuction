"""E2E test configuration and path setup (Plan 7, #36, #67)."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PAYMENT_SERVICE = REPO_ROOT / "services" / "payment-escrow"

if str(PAYMENT_SERVICE) not in sys.path:
    sys.path.insert(0, str(PAYMENT_SERVICE))
