"""Liveness (``/healthz``) and readiness (``/readyz``) endpoints.

Render health checks and the Compose ``healthcheck`` both call ``/healthz``. Services register
dependency checks (database, Redis, Kafka) with :meth:`Readiness.add_check` as they gain them;
``/readyz`` returns 503 until every registered check passes.
"""

import asyncio
from collections.abc import Awaitable, Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse

ReadinessCheck = Callable[[], Awaitable[bool]]

CHECK_TIMEOUT_SECONDS = 2.0


class Readiness:
    def __init__(self) -> None:
        self._checks: dict[str, ReadinessCheck] = {}

    def add_check(self, name: str, check: ReadinessCheck) -> None:
        self._checks[name] = check

    async def _run(self, check: ReadinessCheck) -> bool:
        try:
            return bool(await asyncio.wait_for(check(), CHECK_TIMEOUT_SECONDS))
        except Exception:
            return False

    async def evaluate(self) -> dict[str, bool]:
        names = list(self._checks)
        results = await asyncio.gather(*(self._run(self._checks[name]) for name in names))
        return dict(zip(names, results, strict=True))


def health_router(service_name: str, version: str, readiness: Readiness) -> APIRouter:
    router = APIRouter(tags=["platform"])

    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": service_name, "version": version}

    @router.get("/readyz")
    async def readyz() -> JSONResponse:
        checks = await readiness.evaluate()
        ready = all(checks.values())
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "status": "ready" if ready else "unready",
                "service": service_name,
                "checks": {name: "ok" if ok else "fail" for name, ok in checks.items()},
            },
        )

    return router
