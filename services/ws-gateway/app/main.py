"""WebSocket Gateway — see services/ws-gateway/README.md."""

from zeo_common import create_app

app = create_app(
    service_name="ws-gateway",
    version="0.1.0",
    description="ZeoAuction WebSocket Gateway.",
)
