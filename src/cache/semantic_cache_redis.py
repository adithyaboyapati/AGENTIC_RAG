"""Redis backend for semantic cache entries."""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass
from typing import Any

from src.cache.redis_cache import get_redis_client
from src.config import settings

logger = logging.getLogger(__name__)

_SERIAL_VERSION = 1
_PREFIX = "rag:semcache:v1"


@dataclass
class RedisSemanticEntry:
    question: str
    mode: str
    tenant_id: str
    roles_key: str
    vector: list[float]
    response_json: str
    created_at: float
    pipeline_version: str = "legacy"
    version: int = _SERIAL_VERSION


def _tenant_key(tenant_id: str, roles_key: str) -> str:
    return f"{_PREFIX}:{tenant_id}:{roles_key}"


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=True))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


class RedisSemanticBackend:
    """Shared semantic cache storage in Redis."""

    def lookup(
        self,
        *,
        question: str,
        mode: str,
        tenant_id: str,
        roles_key: str,
        query_vector: list[float],
        pipeline_version: str = "legacy",
    ) -> RedisSemanticEntry | None:
        client = get_redis_client()
        if client is None:
            return None
        key = _tenant_key(tenant_id, roles_key)
        try:
            raw_entries = client.hgetall(key)
        except Exception:
            logger.debug("Semantic cache Redis lookup failed", exc_info=True)
            return None
        if not raw_entries:
            return None

        ttl = max(1, int(settings.cache_ttl_seconds))
        now = time.time()
        threshold = float(settings.semantic_cache_similarity_threshold)
        best: RedisSemanticEntry | None = None
        best_score = -1.0

        for blob in raw_entries.values():
            try:
                data = json.loads(blob)
                if int(data.get("version", 0)) != _SERIAL_VERSION:
                    continue
                if data.get("mode") != mode:
                    continue
                if str(data.get("pipeline_version") or "legacy") != pipeline_version:
                    continue
                created = float(data.get("created_at") or 0.0)
                if (now - created) >= ttl:
                    continue
                vector = data.get("vector") or []
                score = _cosine_similarity(query_vector, vector)
                if score >= threshold and score > best_score:
                    best_score = score
                    best = RedisSemanticEntry(
                        question=str(data.get("question") or ""),
                        mode=str(data.get("mode") or mode),
                        tenant_id=tenant_id,
                        roles_key=roles_key,
                        vector=list(vector),
                        response_json=str(data.get("response_json") or ""),
                        created_at=created,
                        pipeline_version=str(data.get("pipeline_version") or "legacy"),
                    )
            except Exception:
                continue
        return best

    def store(self, entry: RedisSemanticEntry) -> bool:
        client = get_redis_client()
        if client is None:
            return False
        key = _tenant_key(entry.tenant_id, entry.roles_key)
        field = f"{entry.mode}:{entry.created_at}:{hash(entry.question)}"
        payload = json.dumps(
            {
                "version": _SERIAL_VERSION,
                "question": entry.question,
                "mode": entry.mode,
                "pipeline_version": entry.pipeline_version,
                "vector": entry.vector,
                "response_json": entry.response_json,
                "created_at": entry.created_at,
            },
            ensure_ascii=False,
        )
        try:
            pipe = client.pipeline()
            pipe.hset(key, field, payload)
            pipe.expire(key, max(60, int(settings.cache_ttl_seconds)))
            current = client.hlen(key)
            max_entries = max(1, int(settings.semantic_cache_max_entries))
            if current and current > max_entries:
                # Trim oldest fields best-effort.
                fields = client.hkeys(key)
                if len(fields) > max_entries:
                    for old in fields[: len(fields) - max_entries]:
                        pipe.hdel(key, old)
            pipe.execute()
            return True
        except Exception:
            logger.debug("Semantic cache Redis store failed", exc_info=True)
            return False

    def clear(self) -> int:
        client = get_redis_client()
        if client is None:
            return 0
        try:
            keys = list(client.scan_iter(match=f"{_PREFIX}:*"))
            if not keys:
                return 0
            client.delete(*keys)
            return len(keys)
        except Exception:
            logger.debug("Semantic cache Redis clear failed", exc_info=True)
            return 0


_global_backend = RedisSemanticBackend()


def get_redis_semantic_backend() -> RedisSemanticBackend:
    return _global_backend
