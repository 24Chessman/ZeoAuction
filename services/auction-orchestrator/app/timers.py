"""The lifecycle timer: drives A2 open, A5 close and A6 drained when they fall due.

Runs inside each orchestrator instance. Several instances are safe: every transition is
guarded by the version check, so if two instances race for the same auction exactly one wins
and the other skips it (state-machine rule 3).
"""

import asyncio
import logging

from app.service import AuctionService

logger = logging.getLogger(__name__)


class LifecycleTimer:
    def __init__(self, service: AuctionService, interval_seconds: float = 1.0) -> None:
        self.service = service
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None

    async def run(self) -> None:
        while True:
            try:
                await self.service.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Lifecycle timer pass failed")
            await asyncio.sleep(self.interval_seconds)

    def start(self) -> None:
        self._task = asyncio.create_task(self.run(), name="lifecycle-timer")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
