"""Bid batch flusher (worker) — see services/bid-flusher/README.md."""

from zeo_common import create_app

app = create_app(
    service_name="bid-flusher",
    version="0.1.0",
    description="ZeoAuction Bid batch flusher (worker).",
)
