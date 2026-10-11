"""Prometheus ``/metrics`` endpoint (SDD section 9.2).

Each app gets its own registry so services and tests never collide on metric names.
Services register the requirement-specific metrics of SDD Table 9.2 on ``app.state.metrics``.
"""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest


def create_registry(service_name: str, version: str) -> CollectorRegistry:
    registry = CollectorRegistry()
    info = Gauge(
        "zeo_service_info",
        "Static service identity; always 1.",
        ["service", "version"],
        registry=registry,
    )
    info.labels(service=service_name, version=version).set(1)
    return registry


def metrics_router(registry: CollectorRegistry) -> APIRouter:
    router = APIRouter(tags=["platform"])

    @router.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    return router
