"""Admin & Moderation — see services/admin-moderation/README.md."""

from zeo_common import create_app

app = create_app(
    service_name="admin-moderation",
    version="0.1.0",
    description="ZeoAuction Admin & Moderation.",
)
