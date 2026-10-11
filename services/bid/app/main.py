"""Bid Processing — see services/bid/README.md."""

from zeo_common import create_app

app = create_app(
    service_name="bid",
    version="0.1.0",
    description="ZeoAuction Bid Processing.",
)
