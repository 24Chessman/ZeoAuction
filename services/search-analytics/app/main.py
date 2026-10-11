"""Search & Analytics — see services/search-analytics/README.md."""

from zeo_common import create_app

app = create_app(
    service_name="search-analytics",
    version="0.1.0",
    description="ZeoAuction Search & Analytics.",
)
