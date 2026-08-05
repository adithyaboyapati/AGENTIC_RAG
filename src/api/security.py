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


async def verify_api_key(api_key: str | None = Security(api_key_header)) -> None:
    """Require valid API key when enabled."""
    if not auth_required():
        return

    if not settings.api_key:
        raise HTTPException(
            status_code=503,
            detail="API authentication is required but API_KEY is not configured",
        )

    # Constant-time comparison to avoid timing side channels
    if not api_key or not secrets.compare_digest(api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
