"""Redis client + final-answer cache, idempotency store, and key helpers."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from typing import Any

from src.config import settings
from src.schemas import AgentResponse, Citation, RBACContext

logger = logging.getLogger(__name__)

_client: Any | None = None
_client_lock = threading.Lock()
_unavailable_logged = False
_client_failed = False

_CACHE_PREFIX = "rag:v1"
_IDEM_PREFIX = "idem:v1"
_WS_RE = re.compile(r"\s+")


def normalize_question(question: str) -> str:
    """Strip, collapse whitespace, lowercase — stable cache key input."""
    return _WS_RE.sub(" ", (question or "").strip()).lower()


def build_cache_key(
    question: str,
    mode: str,
    rbac_context: RBACContext | None = None,
) -> str:
    ctx = rbac_context or RBACContext()
    tenant = (ctx.tenant_id or "default").strip().lower()
    roles = ctx.roles_key()
    norm_q = normalize_question(question)
    digest = hashlib.sha256(f"{norm_q}:{tenant}:{roles}".encode()).hexdigest()
    return f"{_CACHE_PREFIX}:{mode}:{tenant}:{digest}"


def should_use_cache(
    *,
    use_memory: bool,
    chat_history: list[dict[str, str]] | None,
) -> bool:
    """Skip cache when conversation memory would change the answer."""
    if not settings.cache_enabled:
        return False
    if use_memory and chat_history:
        return False
    return True


def get_redis_client() -> Any | None:
    """Lazy shared Redis client for cache / rate limits / idempotency.

    Connects whenever ``REDIS_URL`` is set; returns None if unreachable.
    Independent of ``CACHE_ENABLED`` so rate limits can share Redis.
    """
    global _client, _unavailable_logged, _client_failed

    if not (settings.redis_url or "").strip():
        return None

    with _client_lock:
        if _client is not None:
            return _client
        if _client_failed:
            return None
        try:
            import redis

            client = redis.Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
            )
            client.ping()
            _client = client
            _unavailable_logged = False
            logger.info("Redis connected (%s)", settings.redis_url)
            return _client
        except Exception:
            _client_failed = True
            if not _unavailable_logged:
                logger.warning(
                    "Redis unavailable — continuing without shared Redis features",
                    exc_info=True,
                )
                _unavailable_logged = True
            return None


# Back-compat alias used by cache helpers / tests
def _get_client() -> Any | None:
    if not settings.cache_enabled:
        return None
    return get_redis_client()


def reset_client_for_tests() -> None:
    """Clear the singleton (tests only)."""
    global _client, _unavailable_logged, _client_failed
    with _client_lock:
        _client = None
        _unavailable_logged = False
        _client_failed = False


def allow_redis_reconnect() -> None:
    """Clear the failure latch so the next get_redis_client() retries."""
    global _client_failed
    with _client_lock:
        if _client is None:
            _client_failed = False


def set_client_for_tests(client: Any | None) -> None:
    """Inject a fake Redis client (tests only)."""
    global _client, _unavailable_logged, _client_failed
    with _client_lock:
        _client = client
        _unavailable_logged = False
        _client_failed = False


def flush_answer_cache() -> int:
    """Delete all ``rag:v1:*`` answer-cache keys. Returns number deleted."""
    client = get_redis_client()
    if client is None:
        return 0
    deleted = 0
    try:
        cursor = 0
        pattern = f"{_CACHE_PREFIX}:*"
        while True:
            cursor, keys = client.scan(cursor=cursor, match=pattern, count=200)
            if keys:
                deleted += int(client.delete(*keys))
            if cursor == 0:
                break
        if deleted:
            logger.info("Flushed %d Redis answer-cache key(s)", deleted)
        return deleted
    except Exception:
        logger.warning("Failed to flush Redis answer cache", exc_info=True)
        return deleted


def _serialize(response: AgentResponse) -> str:
    """JSON payload without bulky context_docs."""
    payload = {
        "answer": response.answer,
        "mode": response.mode,
        "sources": list(response.sources or []),
        "citations": [c.to_dict() for c in (response.citations or [])],
        "route": response.route,
        "route_reason": response.route_reason,
        "grade_summary": response.grade_summary,
        "sub_queries": response.sub_queries,
        "decomposition_reason": response.decomposition_reason,
        "steps": list(response.steps or []),
        "follow_ups": list(response.follow_ups or []),
    }
    return json.dumps(payload, ensure_ascii=False)


def _deserialize(raw: str) -> AgentResponse:
    data = json.loads(raw)
    citations = [
        Citation(
            index=int(c.get("index", i)),
            chunk_id=str(c.get("chunk_id", "")),
            source=str(c.get("source", "unknown")),
            page=c.get("page"),
            section=c.get("section"),
            snippet=str(c.get("snippet") or ""),
            score=c.get("score"),
        )
        for i, c in enumerate(data.get("citations") or [], 1)
    ]
    return AgentResponse(
        answer=str(data.get("answer") or ""),
        mode=str(data.get("mode") or ""),
        sources=list(data.get("sources") or []),
        citations=citations,
        context_docs=[],
        route=data.get("route"),
        route_reason=data.get("route_reason"),
        grade_summary=data.get("grade_summary"),
        sub_queries=data.get("sub_queries"),
        decomposition_reason=data.get("decomposition_reason"),
        steps=list(data.get("steps") or []),
        follow_ups=list(data.get("follow_ups") or []),
    )


def get_cached_response(
    question: str,
    mode: str,
    rbac_context: RBACContext | None = None,
) -> AgentResponse | None:
    """Return a cached AgentResponse (exact or semantic) or None on miss / error."""
    ctx = rbac_context or RBACContext()
    client = _get_client()

    # 1. Try exact Redis cache hit
    if client is not None:
        key = build_cache_key(question, mode, ctx)
        try:
            raw = client.get(key)
            if raw:
                result = _deserialize(raw)
                steps = list(result.steps or [])
                if "cache_hit" not in steps:
                    steps = ["cache_hit", *steps]
                result.steps = steps
                result.tenant_id = ctx.tenant_id
                logger.info("Exact cache hit | mode=%s | key=%s", mode, key)
                try:
                    from src.api.metrics import record_cache_hit

                    record_cache_hit()
                except Exception:
                    pass
                return result
        except Exception:
            logger.warning("Redis GET failed for %s", key, exc_info=True)

    # 2. Try vector-based semantic cache hit
    if settings.cache_enabled and settings.semantic_cache_enabled:
        from src.cache.semantic_cache import get_semantic_cache

        sem_hit = get_semantic_cache().lookup(question, mode, ctx)
        if sem_hit is not None:
            return sem_hit

    return None


def set_cached_response(
    question: str,
    mode: str,
    response: AgentResponse,
    rbac_context: RBACContext | None = None,
) -> bool:
    """Store a successful response in exact and semantic cache. Returns True if written."""
    if not settings.cache_enabled:
        return False
    if getattr(response, "error_code", None):
        return False
    if not response.answer or not response.answer.strip():
        return False

    ctx = rbac_context or RBACContext()
    written = False

    # 1. Store in exact Redis cache if client available
    client = _get_client()
    if client is not None:
        key = build_cache_key(question, mode, ctx)
        ttl = max(1, int(settings.cache_ttl_seconds))
        to_store = AgentResponse(
            answer=response.answer,
            mode=response.mode,
            sources=list(response.sources or []),
            citations=list(response.citations or []),
            context_docs=[],
            route=response.route,
            route_reason=response.route_reason,
            grade_summary=response.grade_summary,
            sub_queries=response.sub_queries,
            decomposition_reason=response.decomposition_reason,
            steps=[s for s in (response.steps or []) if not s.startswith("cache_hit") and not s.startswith("semantic_cache_hit")],
            follow_ups=list(response.follow_ups or []),
            tenant_id=ctx.tenant_id,
        )
        try:
            client.setex(key, ttl, _serialize(to_store))
            logger.debug("Exact cache set | mode=%s | ttl=%ds | key=%s", mode, ttl, key)
            try:
                from src.api.metrics import record_cache_miss_write

                record_cache_miss_write()
            except Exception:
                pass
            written = True
        except Exception:
            logger.warning("Redis SET failed for %s", key, exc_info=True)

    # 2. Store in semantic cache
    if settings.semantic_cache_enabled:
        from src.cache.semantic_cache import get_semantic_cache

        sem_written = get_semantic_cache().store(question, mode, response, ctx)
        written = written or sem_written

    return written


# ---------------------------------------------------------------------------
# Idempotency (POST /query)
# ---------------------------------------------------------------------------


def build_idempotency_key(key: str) -> str:
    digest = hashlib.sha256(key.strip().encode("utf-8")).hexdigest()
    return f"{_IDEM_PREFIX}:{digest}"


def get_idempotent_response(key: str) -> dict[str, Any] | None:
    """Return stored ``{body_hash, response}`` or None."""
    client = get_redis_client()
    if client is None or not key.strip():
        return None
    redis_key = build_idempotency_key(key)
    try:
        raw = client.get(redis_key)
        if not raw:
            return None
        data = json.loads(raw)
        if not isinstance(data, dict) or "body_hash" not in data or "response" not in data:
            return None
        return data
    except Exception:
        logger.warning("Idempotency GET failed", exc_info=True)
        return None


def set_idempotent_response(key: str, body_hash: str, response: dict[str, Any]) -> bool:
    client = get_redis_client()
    if client is None or not key.strip():
        return False
    redis_key = build_idempotency_key(key)
    ttl = max(1, int(settings.idempotency_ttl_seconds))
    try:
        payload = json.dumps({"body_hash": body_hash, "response": response}, ensure_ascii=False)
        client.setex(redis_key, ttl, payload)
        return True
    except Exception:
        logger.warning("Idempotency SET failed", exc_info=True)
        return False
