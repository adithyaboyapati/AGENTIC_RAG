"""Shadow/canary execution context — prevents side effects during evaluation."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_SHADOW_EXECUTION: ContextVar[bool] = ContextVar("shadow_execution", default=False)
_CANARY_EXECUTION: ContextVar[bool] = ContextVar("canary_execution", default=False)
_REPLAY_EXECUTION: ContextVar[bool] = ContextVar("replay_execution", default=False)


def is_shadow_execution() -> bool:
    return _SHADOW_EXECUTION.get()


def is_canary_execution() -> bool:
    return _CANARY_EXECUTION.get()


def is_replay_execution() -> bool:
    return _REPLAY_EXECUTION.get()


def is_observational_execution() -> bool:
    """True when the run must not mutate production user-visible state."""
    return is_shadow_execution() or is_replay_execution() or is_canary_execution()


@contextmanager
def shadow_execution():
    token = _SHADOW_EXECUTION.set(True)
    try:
        yield
    finally:
        _SHADOW_EXECUTION.reset(token)


@contextmanager
def canary_execution():
    token = _CANARY_EXECUTION.set(True)
    try:
        yield
    finally:
        _CANARY_EXECUTION.reset(token)


@contextmanager
def replay_execution():
    token = _REPLAY_EXECUTION.set(True)
    try:
        yield
    finally:
        _REPLAY_EXECUTION.reset(token)
