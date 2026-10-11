"""Auth & User Service — see services/auth-user/README.md."""

from zeo_common import create_app

app = create_app(
    service_name="auth-user",
    version="0.1.0",
    description="ZeoAuction Auth & User Service.",
)
