"""Circuit breaker unit tests."""

from __future__ import annotations

import time

import pytest

from src.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    reset_breakers_for_tests,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_breakers_for_tests()
    yield
    reset_breakers_for_tests()


def test_opens_after_threshold_failures():
    breaker = CircuitBreaker("t", failure_threshold=3, recovery_timeout=60)

    def boom():
        raise RuntimeError("fail")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            breaker.call(boom)

    assert breaker.state == "open"
    with pytest.raises(CircuitOpenError):
        breaker.call(lambda: "ok")


def test_recovers_after_timeout():
    breaker = CircuitBreaker("t2", failure_threshold=1, recovery_timeout=0.05)

    with pytest.raises(RuntimeError):
        breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))

    assert breaker.state == "open"
    time.sleep(0.06)
    assert breaker.call(lambda: "ok") == "ok"
    assert breaker.state == "closed"
