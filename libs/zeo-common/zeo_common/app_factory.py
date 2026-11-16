"""The service template: every ZeoAuction service is created by :func:`create_app`."""

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from zeo_common.errors import install_error_handlers
from zeo_common.health import Readiness, health_router
from zeo_common.logging_setup import configure_logging
from zeo_common.metrics import create_registry, metrics_router
from zeo_common.request_context import RequestIdMiddleware

API_PREFIX = "/api/v1"
logger = logging.getLogger("zeo.app")


def cors_origins() -> list[str]:
    """Comma-separated ``CORS_ALLOW_ORIGINS``; empty (no CORS) unless configured."""
    raw = os.environ.get("CORS_ALLOW_ORIGINS", "")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if origins:
        extended = list(origins)
        for o in origins:
            if "localhost" in o:
                alt = o.replace("localhost", "127.0.0.1")
                if alt not in extended:
                    extended.append(alt)
            elif "127.0.0.1" in o:
                alt = o.replace("127.0.0.1", "localhost")
                if alt not in extended:
                    extended.append(alt)
        return extended
    return []


def create_app(service_name: str, version: str = "0.1.0", description: str = "") -> FastAPI:
    """Build a FastAPI app with the platform conventions already wired in.

    Services add their own routers under :data:`API_PREFIX` and register readiness checks
    on ``app.state.readiness``.
    """
    configure_logging(service_name)
    logger.info("Initializing ZeoAuction service '%s' (v%s)", service_name, version)

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
        logger.info("[%s] CORS allowed origins: %s", service_name, origins)
        # The SPA calls the APIs directly in local development (Vite on :5173).
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID", "Idempotent-Replay"],
        )
    else:
        logger.info("[%s] No service-level CORS set; CORS handled centrally by API Gateway", service_name)
    install_error_handlers(app)
    app.include_router(health_router(service_name, version, app.state.readiness))
    app.include_router(metrics_router(app.state.metrics))
    return app
