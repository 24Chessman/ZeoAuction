"""Auction Orchestration — see services/auction-orchestrator/README.md."""

from zeo_common import create_app

app = create_app(
    service_name="auction-orchestrator",
    version="0.1.0",
    description="ZeoAuction Auction Orchestration.",
)
