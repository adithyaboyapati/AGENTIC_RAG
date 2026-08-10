"""Per-client rate limiting (sliding window).

Backend: Redis (shared across workers) with in-memory fallback.
Keyed by API key when present, else client IP (optionally X-Forwarded-For).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from src.config import settings

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 60.0
_RATE_PREFIX = "ratelimit:v1"

# Sweep idle clients out of the in-memory window. Without this the dict keeps
# one entry per distinct IP seen since boot — an unbounded leak on a public
# endpoint, even though each individual deque is emptied.
_PRUNE_INTERVAL_SECONDS = 60.0
_MAX_TRACKED_CLIENTS = 10_000

_history: dict[str, deque[float]] = defaultdict(deque)
_history_lock = threading.Lock()
_last_prune = 0.0

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _prune_history(now: float) -> None:
    """Drop clients with no activity inside the window (amortised, O(n))."""
    global _last_prune
    if now - _last_prune < _PRUNE_INTERVAL_SECONDS:
        return
    _last_prune = now

    stale = [
        key
        for key, window in _history.items()
        if not window or now - window[-1] > _WINDOW_SECONDS
    ]
    for key in stale:
        _history.pop(key, None)

    if len(_history) > _MAX_TRACKED_CLIENTS:
        # Pathological cardinality (spoofed XFF, botnet). Keep the most recent
        # talkers and let the rest re-enter with a fresh window.
        newest = sorted(
            _history.items(), key=lambda kv: kv[1][-1] if kv[1] else 0.0, reverse=True
        )[:_MAX_TRACKED_CLIENTS]
        _history.clear()
        _history.update(newest)
        logger.warning(
            "Rate-limit table exceeded %d clients — truncated", _MAX_TRACKED_CLIENTS
        )


def _client_id(request: Request, api_key: str | None) -> str:
    if api_key:
        return f"key:{api_key}"
    if settings.trust_proxy_headers:
        forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if forwarded:
            return f"ip:{forwarded}"
    if request.client:
        return f"ip:{request.client.host}"
    return "ip:unknown"


def _use_redis_backend() -> bool:
    backend = (settings.rate_limit_backend or "auto").strip().lower()
    if backend == "memory":
        return False
    # auto | redis → try Redis
    return True


def _enforce_memory(client_id: str, limit: int) -> None:
    now = time.monotonic()

    with _history_lock:
        _prune_history(now)
        window = _history[client_id]

        while window and now - window[0] > _WINDOW_SECONDS:
            window.popleft()

        over_limit = len(window) >= limit
        retry_after = (
            max(1, int(_WINDOW_SECONDS - (now - window[0])) + 1) if window else 1
        )
        if not over_limit:
            window.append(now)

    if over_limit:
        try:
            from src.api.metrics import record_rate_limit_hit

            record_rate_limit_hit()
        except Exception:
            pass
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded ({limit} requests/minute). Try again later.",
            headers={"Retry-After": str(retry_after)},
        )


def _enforce_redis(client_id: str, limit: int) -> bool:
    """Return True if enforced via Redis; False if Redis unavailable."""
    from src.cache.redis_cache import get_redis_client

    client = get_redis_client()
    if client is None:
        return False

    key = f"{_RATE_PREFIX}:{client_id}"
    now = time.time()
    window_start = now - _WINDOW_SECONDS
    try:
        pipe = client.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zcard(key)
        pipe.zadd(key, {f"{now}": now})
        pipe.expire(key, int(_WINDOW_SECONDS) + 1)
        results = pipe.execute()
        count = int(results[1])
        if count >= limit:
            # Undo the add we just performed
            try:
                client.zrem(key, f"{now}")
            except Exception:
                pass
            try:
                from src.api.metrics import record_rate_limit_hit

                record_rate_limit_hit()
            except Exception:
                pass
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded ({limit} requests/minute). Try again later.",
                headers={"Retry-After": "60"},
            )
        return True
    except HTTPException:
        raise
    except Exception:
        logger.warning("Redis rate limit failed — falling back to memory", exc_info=True)
        return False


async def enforce_client_rate_limit(
    request: Request,
    api_key: str | None = Security(_api_key_header),
) -> None:
    """FastAPI dependency: reject clients exceeding their per-minute quota."""
    limit = settings.max_queries_per_minute_per_client
    if limit <= 0:
        return

    client_id = _client_id(request, api_key)
    if _use_redis_backend():
        if _enforce_redis(client_id, limit):
            return
        if (settings.rate_limit_backend or "").strip().lower() == "redis":
            logger.warning("rate_limit_backend=redis but Redis down — using memory fallback")
    _enforce_memory(client_id, limit)
