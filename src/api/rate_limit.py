"""Per-client rate limiting (sliding window, in-memory).

Keyed by API key when present, else client IP. Suitable for a single-process
deployment; move to a Redis-backed limiter before scaling to multiple
workers or replicas.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from src.config import settings

_WINDOW_SECONDS = 60.0

_history: dict[str, deque[float]] = defaultdict(deque)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _client_id(request: Request, api_key: str | None) -> str:
    if api_key:
        return f"key:{api_key}"
    if request.client:
        return f"ip:{request.client.host}"
    return "ip:unknown"


async def enforce_client_rate_limit(
    request: Request,
    api_key: str | None = Security(_api_key_header),
) -> None:
    """FastAPI dependency: reject clients exceeding their per-minute quota."""
    limit = settings.max_queries_per_minute_per_client
    if limit <= 0:
        return

    now = time.monotonic()
    window = _history[_client_id(request, api_key)]

    while window and now - window[0] > _WINDOW_SECONDS:
        window.popleft()

    if len(window) >= limit:
        retry_after = max(1, int(_WINDOW_SECONDS - (now - window[0])) + 1)
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded ({limit} requests/minute). Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    window.append(now)
