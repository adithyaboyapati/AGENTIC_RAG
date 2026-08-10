"""API authentication and rate-limit helpers."""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from src.config import is_production, settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def auth_required() -> bool:
    """Auth is always required in production, opt-in elsewhere."""
    return settings.require_api_key or is_production()


def _check_key(api_key: str | None) -> None:
    if not settings.api_key:
        raise HTTPException(
            status_code=503,
            detail="API authentication is required but API_KEY is not configured",
        )

    # Constant-time comparison to avoid timing side channels
    if not api_key or not secrets.compare_digest(api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


async def verify_api_key(api_key: str | None = Security(api_key_header)) -> None:
    """Require valid API key when enabled."""
    if not auth_required():
        return
    _check_key(api_key)


def _verify_operational_access(api_key: str | None, *, enabled: bool, name: str) -> None:
    """Gate an operational endpoint.

    Protected independently of ``REQUIRE_API_KEY``: a scrape target is reachable
    long before app auth is switched on, and these payloads describe internal
    topology.

    When no ``API_KEY`` is configured there is nothing to check. Rather than
    503-ing every probe on a developer laptop, this falls open outside
    production — and in production it cannot happen, because
    ``_validate_production_config`` refuses to start without a key.
    """
    if not enabled:
        return
    if not settings.api_key:
        if is_production():
            raise HTTPException(
                status_code=503,
                detail=f"{name} is protected but API_KEY is not configured",
            )
        return
    _check_key(api_key)


async def verify_metrics_access(api_key: str | None = Security(api_key_header)) -> None:
    """Gate /metrics. Disable with ``PROTECT_METRICS_ENDPOINT=false``."""
    _verify_operational_access(
        api_key, enabled=settings.protect_metrics_endpoint, name="/metrics"
    )


async def verify_readiness_access(
    api_key: str | None = Security(api_key_header),
) -> None:
    """Gate /health/ready — see ``_verify_operational_access``.

    ``/health`` stays public so liveness probes and load balancers keep working
    without credentials.
    """
    _verify_operational_access(
        api_key, enabled=settings.protect_readiness_endpoint, name="/health/ready"
    )
