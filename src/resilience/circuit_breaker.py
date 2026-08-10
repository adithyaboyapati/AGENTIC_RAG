"""Simple in-process circuit breaker (closed → open → half-open)."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, TypeVar
from collections.abc import Callable

from src.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = threading.Lock()


class CircuitOpenError(RuntimeError):
    """Raised when the circuit is open and calls are short-circuited."""


class CircuitBreaker:
    """Fail-fast after consecutive failures; allow a trial call after recovery timeout."""

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int | None = None,
        recovery_timeout: float | None = None,
    ):
        self.name = name
        self.failure_threshold = failure_threshold or settings.circuit_breaker_failure_threshold
        self.recovery_timeout = recovery_timeout or float(settings.circuit_breaker_recovery_seconds)
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open = False
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._opened_at is None:
                return "closed"
            if self._half_open:
                return "half_open"
            if time.monotonic() - self._opened_at >= self.recovery_timeout:
                return "half_open"
            return "open"

    def allow(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return True
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self.recovery_timeout:
                self._half_open = True
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._half_open = False

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                if self._opened_at is None:
                    logger.warning(
                        "Circuit breaker OPEN | name=%s | failures=%d",
                        self.name,
                        self._failures,
                    )
                self._opened_at = time.monotonic()
                self._half_open = False

    def call(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        if not self.allow():
            raise CircuitOpenError(f"Circuit '{self.name}' is open")
        try:
            result = fn(*args, **kwargs)
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result


def get_breaker(name: str) -> CircuitBreaker:
    with _breakers_lock:
        if name not in _breakers:
            _breakers[name] = CircuitBreaker(name)
        return _breakers[name]


def reset_breakers_for_tests() -> None:
    with _breakers_lock:
        _breakers.clear()
