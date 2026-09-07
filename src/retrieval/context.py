"""Request-scoped RBAC context so every retrieve() call inherits the caller."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator

from src.schemas import RBACContext

_rbac_var: ContextVar[RBACContext | None] = ContextVar("rbac_context", default=None)


def current_rbac() -> RBACContext:
    return _rbac_var.get() or RBACContext()


@contextmanager
def use_rbac_context(ctx: RBACContext | None) -> Iterator[RBACContext]:
    resolved = ctx if isinstance(ctx, RBACContext) else RBACContext()
    token = _rbac_var.set(resolved)
    try:
        yield resolved
    finally:
        _rbac_var.reset(token)
