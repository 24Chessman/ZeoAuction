"""Payment, Fees & Escrow — see services/payment-escrow/README.md."""

from zeo_common import create_app

app = create_app(
    service_name="payment-escrow",
    version="0.1.0",
    description="ZeoAuction Payment, Fees & Escrow. Test mode only: escrow is a simulation.",
)
