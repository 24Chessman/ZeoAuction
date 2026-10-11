"""Circuit breaker for the synchronous boundaries of SDD Table 2.2 (CT-1, CT-3, Payment).

Opens after ``failure_threshold`` failures within ``window_seconds``; successes in between
do not reset the count, so a dependency failing half the time still trips it. While open,
calls fail fast with :class:`CircuitOpen` and the caller uses its declared fallback. After
``reset_seconds`` one trial call is let through (half-open): success closes the breaker,
failure re-opens it.
"""

import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"


class CircuitOpen(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"circuit {name} is open")
        self.name = name


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 5,
        window_seconds: float = 10.0,
        reset_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.window_seconds = window_seconds
        self.reset_seconds = reset_seconds
        self._clock = clock
        self._failures: deque[float] = deque()
        self._opened_at: float | None = None
        self._trial_in_flight = False

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return CLOSED
        if self._clock() - self._opened_at >= self.reset_seconds:
            return HALF_OPEN
        return OPEN

    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        state = self.state
        if state == OPEN or (state == HALF_OPEN and self._trial_in_flight):
            raise CircuitOpen(self.name)
        trial = state == HALF_OPEN
        self._trial_in_flight = trial
        try:
            result = await fn()
        except Exception:
            self._record_failure(trial)
            raise
        finally:
            if trial:
                self._trial_in_flight = False
        if trial:
            self._failures.clear()
            self._opened_at = None
        return result

    def _record_failure(self, trial: bool) -> None:
        now = self._clock()
        if trial:
            self._opened_at = now
            return
        self._failures.append(now)
        while self._failures and now - self._failures[0] > self.window_seconds:
            self._failures.popleft()
        if len(self._failures) >= self.failure_threshold:
            self._opened_at = now
