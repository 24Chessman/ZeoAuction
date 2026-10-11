"""Pricing Engine — see services/pricing/README.md."""

from zeo_common import create_app

app = create_app(
    service_name="pricing",
    version="0.1.0",
    description="ZeoAuction Pricing Engine.",
)
