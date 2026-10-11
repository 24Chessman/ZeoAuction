"""The service template: every ZeoAuction service is created by :func:`create_app`."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from zeo_common.errors import install_error_handlers
from zeo_common.health import Readiness, health_router
from zeo_common.logging_setup import configure_logging
from zeo_common.metrics import create_registry, metrics_router
from zeo_common.request_context import RequestIdMiddleware

API_PREFIX = "/api/v1"


def cors_origins() -> list[str]:
    """Comma-separated ``CORS_ALLOW_ORIGINS``; empty (no CORS) unless configured."""
    raw = os.environ.get("CORS_ALLOW_ORIGINS", "")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app(service_name: str, version: str = "0.1.0", description: str = "") -> FastAPI:
    """Build a FastAPI app with the platform conventions already wired in.

    Services add their own routers under :data:`API_PREFIX` and register readiness checks
    on ``app.state.readiness``.
    """
    configure_logging(service_name)

    app = FastAPI(
        title=f"ZeoAuction {service_name}",
        version=version,
        description=description,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    app.state.service_name = service_name
    app.state.readiness = Readiness()
    app.state.metrics = create_registry(service_name, version)

    app.add_middleware(RequestIdMiddleware)
    origins = cors_origins()
    if origins:
        # The SPA calls the APIs directly in local development (Vite on :5173).
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
            expose_headers=["X-Request-ID", "Idempotent-Replay"],
        )
    install_error_handlers(app)
    app.include_router(health_router(service_name, version, app.state.readiness))
    app.include_router(metrics_router(app.state.metrics))
    return app
