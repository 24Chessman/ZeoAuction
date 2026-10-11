import pytest

from zeo_common.circuit_breaker import CLOSED, HALF_OPEN, OPEN, CircuitBreaker, CircuitOpen


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def ok():
    return "ok"


async def boom():
    raise ConnectionError("down")


def breaker(clock: Clock) -> CircuitBreaker:
    return CircuitBreaker("payment", failure_threshold=3, window_seconds=30,
                          reset_seconds=5, clock=clock)


async def fail(cb: CircuitBreaker, times: int) -> None:
    for _ in range(times):
        with pytest.raises(ConnectionError):
            await cb.call(boom)


async def test_opens_after_the_threshold_within_the_window():
    clock = Clock()
    cb = breaker(clock)
    await fail(cb, 2)
    assert cb.state == CLOSED
    await fail(cb, 1)
    assert cb.state == OPEN
    with pytest.raises(CircuitOpen):
        await cb.call(ok)


async def test_failures_outside_the_window_are_forgotten():
    clock = Clock()
    cb = breaker(clock)
    await fail(cb, 2)
    clock.now = 31
    await fail(cb, 2)
    assert cb.state == CLOSED


async def test_half_open_trial_closes_or_reopens():
    clock = Clock()
    cb = breaker(clock)
    await fail(cb, 3)
    clock.now = 5
    assert cb.state == HALF_OPEN
    await fail(cb, 1)
    assert cb.state == OPEN
    clock.now = 10
    assert await cb.call(ok) == "ok"
    assert cb.state == CLOSED
