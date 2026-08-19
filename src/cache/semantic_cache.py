"""
Vector-Based Semantic Caching for Agentic RAG.

Provides sub-50ms responses for semantically equivalent questions using
cosine similarity over query embeddings. Supports multi-tenant & RBAC isolation.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass

from src.config import settings
from src.schemas import AgentResponse, RBACContext

logger = logging.getLogger(__name__)


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=True))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


@dataclass
class _SemanticCacheEntry:
    question: str
    mode: str
    tenant_id: str
    roles_key: str
    vector: list[float]
    response_json: str
    created_at: float


class SemanticCache:
    """Thread-safe vector semantic cache with in-memory store and optional Redis sync."""

    def __init__(self, max_entries: int = 1000) -> None:
        self.max_entries = max_entries
        self._lock = threading.Lock()
        self._entries: list[_SemanticCacheEntry] = []

    def _get_embedding(self, text: str) -> list[float] | None:
        """Compute embedding vector for the text using the project's embedding model."""
        try:
            from src.ingestion.ingest import get_embeddings

            embeddings = get_embeddings()
            return embeddings.embed_query(text)
        except Exception:
            logger.debug("Failed to compute embedding for semantic cache", exc_info=True)
            return None

    def lookup(
        self,
        question: str,
        mode: str,
        rbac_context: RBACContext | None = None,
    ) -> AgentResponse | None:
        """Look up semantically equivalent question in cache."""
        if not settings.cache_enabled or not settings.semantic_cache_enabled:
            return None

        ctx = rbac_context or RBACContext()
        tenant_id = (ctx.tenant_id or "default").strip().lower()
        roles_key = ctx.roles_key()

        query_vec = self._get_embedding(question)
        if query_vec is None:
            return None

        best_score = -1.0
        best_entry: _SemanticCacheEntry | None = None
        now = time.time()
        ttl = max(1, int(settings.cache_ttl_seconds))

        with self._lock:
            # Evict expired entries
            self._entries = [e for e in self._entries if (now - e.created_at) < ttl]

            for entry in self._entries:
                if entry.mode != mode:
                    continue
                if entry.tenant_id != tenant_id or entry.roles_key != roles_key:
                    continue

                sim = _cosine_similarity(query_vec, entry.vector)
                if sim > best_score:
                    best_score = sim
                    best_entry = entry

        threshold = float(settings.semantic_cache_similarity_threshold)
        if best_entry is not None and best_score >= threshold:
            logger.info(
                "Semantic cache hit | mode=%s | score=%.4f (>= %.2f) | query=%r matched cached=%r",
                mode,
                best_score,
                threshold,
                question[:80],
                best_entry.question[:80],
            )
            try:
                from src.cache.redis_cache import _deserialize

                res = _deserialize(best_entry.response_json)
                steps = list(res.steps or [])
                if "semantic_cache_hit" not in steps:
                    steps = [f"semantic_cache_hit(score={best_score:.3f})", *steps]
                res.steps = steps
                res.tenant_id = tenant_id

                try:
                    from src.api.metrics import record_cache_hit

                    record_cache_hit()
                except Exception:
                    pass

                return res
            except Exception:
                logger.warning("Failed to deserialize semantic cache entry", exc_info=True)
                return None

        return None

    def store(
        self,
        question: str,
        mode: str,
        response: AgentResponse,
        rbac_context: RBACContext | None = None,
    ) -> bool:
        """Store response in semantic cache."""
        if not settings.cache_enabled or not settings.semantic_cache_enabled:
            return False
        if getattr(response, "error_code", None):
            return False
        if not response.answer or not response.answer.strip():
            return False

        ctx = rbac_context or RBACContext()
        tenant_id = (ctx.tenant_id or "default").strip().lower()
        roles_key = ctx.roles_key()

        query_vec = self._get_embedding(question)
        if query_vec is None:
            return False

        from src.cache.redis_cache import _serialize

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
            tenant_id=tenant_id,
        )
        payload = _serialize(to_store)

        entry = _SemanticCacheEntry(
            question=question,
            mode=mode,
            tenant_id=tenant_id,
            roles_key=roles_key,
            vector=query_vec,
            response_json=payload,
            created_at=time.time(),
        )

        with self._lock:
            # Maintain capacity
            if len(self._entries) >= self.max_entries:
                self._entries.pop(0)
            self._entries.append(entry)

        logger.debug(
            "Stored in semantic cache | mode=%s | tenant=%s | entries=%d",
            mode,
            tenant_id,
            len(self._entries),
        )
        return True

    def clear(self) -> int:
        """Clear in-memory semantic cache entries. Returns count cleared."""
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            return count


# Singleton semantic cache instance
_global_semantic_cache = SemanticCache()


def get_semantic_cache() -> SemanticCache:
    return _global_semantic_cache
