"""KYC & Seller Verification — see services/kyc/README.md."""

from zeo_common import create_app

app = create_app(
    service_name="kyc",
    version="0.1.0",
    description="ZeoAuction KYC & Seller Verification.",
)
