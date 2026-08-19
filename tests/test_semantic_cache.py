"""Tests for Vector-Based Semantic Caching."""

import pytest

from src.cache.semantic_cache import SemanticCache, _cosine_similarity
from src.config import settings
from src.schemas import AgentResponse, Citation, RBACContext


def test_cosine_similarity():
    vec_a = [1.0, 0.0, 0.0]
    vec_b = [1.0, 0.0, 0.0]
    assert pytest.approx(_cosine_similarity(vec_a, vec_b), 0.001) == 1.0

    vec_c = [0.0, 1.0, 0.0]
    assert pytest.approx(_cosine_similarity(vec_a, vec_c), 0.001) == 0.0

    # Empty / mismatched length
    assert _cosine_similarity([], [1.0]) == 0.0
    assert _cosine_similarity([1.0, 2.0], [1.0]) == 0.0


def test_semantic_cache_store_and_lookup():
    cache = SemanticCache()

    # Inject a deterministic embedding mock for the test
    # (or let it compute if embeddings are available)
    def mock_embed(text: str) -> list[float]:
        # Simple bag-of-words / char hash based vector for test determinism
        if "crag" in text.lower() or "corrective" in text.lower():
            return [0.9, 0.4, 0.1]
        elif "self-rag" in text.lower():
            return [0.1, 0.9, 0.1]
        return [0.0, 0.1, 0.9]

    cache._get_embedding = mock_embed

    orig_enabled = settings.cache_enabled
    orig_sem_enabled = settings.semantic_cache_enabled
    orig_thresh = settings.semantic_cache_similarity_threshold

    settings.cache_enabled = True
    settings.semantic_cache_enabled = True
    settings.semantic_cache_similarity_threshold = 0.85

    try:
        response = AgentResponse(
            answer="Corrective RAG (CRAG) is an approach that evaluates retrieved documents.",
            mode="crag",
            sources=["doc1.pdf"],
            citations=[Citation(index=1, chunk_id="c1", source="doc1.pdf", snippet="CRAG text")],
        )

        stored = cache.store("What is corrective RAG?", "crag", response)
        assert stored

        # Semantically close query (similar vector)
        hit = cache.lookup("Explain CRAG architecture", "crag")
        assert hit is not None
        assert "Corrective RAG" in hit.answer
        assert any("semantic_cache_hit" in s for s in hit.steps)

        # Semantically different query
        miss = cache.lookup("What is Self-RAG?", "crag")
        assert miss is None
    finally:
        settings.cache_enabled = orig_enabled
        settings.semantic_cache_enabled = orig_sem_enabled
        settings.semantic_cache_similarity_threshold = orig_thresh


def test_semantic_cache_tenant_and_role_isolation():
    cache = SemanticCache()
    cache._get_embedding = lambda text: [1.0, 0.0, 0.0]

    orig_enabled = settings.cache_enabled
    orig_sem_enabled = settings.semantic_cache_enabled
    settings.cache_enabled = True
    settings.semantic_cache_enabled = True
    settings.semantic_cache_similarity_threshold = 0.9

    try:
        resp_tenant_a = AgentResponse(
            answer="Tenant A confidential report",
            mode="baseline",
            sources=["tenant_a_doc.pdf"],
        )
        ctx_a = RBACContext(tenant_id="tenant_a", user_roles=["admin"])
        cache.store("Company confidential revenue", "baseline", resp_tenant_a, ctx_a)

        # Query from Tenant A -> Hit
        hit_a = cache.lookup("Company confidential revenue", "baseline", ctx_a)
        assert hit_a is not None
        assert hit_a.answer == "Tenant A confidential report"

        # Query from Tenant B -> Must be a Miss (isolated!)
        ctx_b = RBACContext(tenant_id="tenant_b", user_roles=["admin"])
        hit_b = cache.lookup("Company confidential revenue", "baseline", ctx_b)
        assert hit_b is None

        # Query from Tenant A with unprivileged public role -> Must be a Miss
        ctx_a_public = RBACContext(tenant_id="tenant_a", user_roles=["public"])
        hit_a_public = cache.lookup("Company confidential revenue", "baseline", ctx_a_public)
        assert hit_a_public is None
    finally:
        settings.cache_enabled = orig_enabled
        settings.semantic_cache_enabled = orig_sem_enabled
