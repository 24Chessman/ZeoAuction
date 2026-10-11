"""Dispute Management — see services/dispute/README.md."""

from zeo_common import create_app

app = create_app(
    service_name="dispute",
    version="0.1.0",
    description="ZeoAuction Dispute Management.",
)
