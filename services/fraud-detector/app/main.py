"""Fraud Detection (worker) — see services/fraud-detector/README.md."""

from zeo_common import create_app

# Worker: the HTTP surface is health and metrics only. The consumer loop is added
# in #51 dataset (Plan 2), #52 (Plan 4).

app = create_app(
    service_name="fraud-detector",
    version="0.1.0",
    description="ZeoAuction Fraud Detection (worker).",
)
