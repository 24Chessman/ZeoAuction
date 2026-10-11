"""The settlement worker: retries parked captures, resumes interrupted ones and expires
unpaid orders (:meth:`app.service.PaymentService.run_due_work`).

Runs inside each payment instance. Several instances are safe: every order write carries the
version check, so if two instances race for one order exactly one wins and the other skips it.
"""

import asyncio
import logging

from app.service import PaymentService

logger = logging.getLogger(__name__)


class SettlementWorker:
    def __init__(self, service: PaymentService, interval_seconds: float = 5.0) -> None:
        self.service = service
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None

    async def run(self) -> None:
        while True:
            try:
                await self.service.run_due_work()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Settlement worker pass failed")
            await asyncio.sleep(self.interval_seconds)

    def start(self) -> None:
        self._task = asyncio.create_task(self.run(), name="settlement-worker")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
