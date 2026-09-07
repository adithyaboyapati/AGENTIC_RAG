"""OpenTelemetry tracing for the canonical workflow (optional)."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from src.config import settings

logger = logging.getLogger(__name__)

_tracer = None
_tracer_checked = False


def _get_tracer():
    global _tracer, _tracer_checked
    if _tracer_checked:
        return _tracer
    _tracer_checked = True
    if not settings.otel_enabled:
        return None
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider

        resource = Resource.create({"service.name": settings.otel_service_name})
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(settings.otel_service_name)
    except Exception:
        logger.debug("OpenTelemetry unavailable; canonical tracing disabled", exc_info=True)
        _tracer = None
    return _tracer


@contextmanager
def canonical_span(
    name: str,
    *,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Create a canonical workflow span with safe attributes only."""
    tracer = _get_tracer()
    if tracer is None:
        yield None
        return
    safe = {k: v for k, v in (attributes or {}).items() if v is not None}
    with tracer.start_as_current_span(name, attributes=safe) as span:
        yield span


def start_request_trace(
    *,
    request_id: str,
    tenant_id: str,
    route: str | None = None,
    strategy: str | None = None,
) -> Any:
    tracer = _get_tracer()
    if tracer is None:
        return None
    span = tracer.start_span(
        "canonical.request",
        attributes={
            "request_id": request_id,
            "tenant_id": tenant_id,
            "route": route or "",
            "strategy": strategy or "",
        },
    )
    return span
