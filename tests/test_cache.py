"""Unit tests for Redis response cache (mocked client — no Redis required)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.cache.redis_cache import (
    build_cache_key,
    flush_answer_cache,
    get_cached_response,
    normalize_question,
    reset_client_for_tests,
    set_cached_response,
    set_client_for_tests,
    should_use_cache,
)
from src.schemas import AgentResponse, Citation


@pytest.fixture(autouse=True)
def _reset_cache_client():
    reset_client_for_tests()
    yield
    reset_client_for_tests()


def test_normalize_question_collapses_whitespace_and_case():
    assert normalize_question("  What   Is   RAG?  ") == "what is rag?"


def test_build_cache_key_stable_for_equivalent_questions():
    a = build_cache_key("What is RAG?", "crag")
    b = build_cache_key("  what   is   rag? ", "crag")
    assert a == b
    assert a.startswith("rag:v1:crag:")


def test_build_cache_key_differs_by_mode():
    assert build_cache_key("What is RAG?", "crag") != build_cache_key("What is RAG?", "baseline")


def test_should_use_cache_respects_flag_and_memory(monkeypatch):
    monkeypatch.setattr("src.cache.redis_cache.settings.cache_enabled", False)
    assert should_use_cache(use_memory=False, chat_history=None) is False

    monkeypatch.setattr("src.cache.redis_cache.settings.cache_enabled", True)
    assert should_use_cache(use_memory=False, chat_history=None) is True
    assert should_use_cache(use_memory=True, chat_history=None) is True
    assert should_use_cache(
        use_memory=True,
        chat_history=[{"role": "user", "content": "hi"}],
    ) is False


def test_get_set_roundtrip_with_fake_redis(monkeypatch):
    monkeypatch.setattr("src.cache.redis_cache.settings.cache_enabled", True)
    monkeypatch.setattr("src.cache.redis_cache.settings.cache_ttl_seconds", 3600)

    store: dict[str, str] = {}
    fake = MagicMock()
    fake.get.side_effect = lambda k: store.get(k)
    fake.setex.side_effect = lambda k, ttl, v: store.__setitem__(k, v)

    set_client_for_tests(fake)

    original = AgentResponse(
        answer="RAG retrieves then generates.",
        mode="baseline",
        sources=["rag.pdf#p1"],
        citations=[
            Citation(
                index=1,
                chunk_id="c1",
                source="rag.pdf",
                page=1,
                section="Intro",
                snippet="RAG retrieves...",
                score=0.9,
            )
        ],
        context_docs=["bulky context should not be cached"],
        steps=["retrieve", "generate"],
        follow_ups=["What is Self-RAG?"],
    )

    assert set_cached_response("What is RAG?", "baseline", original) is True
    fake.setex.assert_called_once()
    assert fake.setex.call_args.args[1] == 3600

    hit = get_cached_response("What is RAG?", "baseline")
    assert hit is not None
    assert hit.answer == original.answer
    assert hit.sources == original.sources
    assert hit.follow_ups == original.follow_ups
    assert hit.citations[0].chunk_id == "c1"
    assert hit.context_docs == []
    assert hit.steps[0] == "cache_hit"
    assert "retrieve" in hit.steps


def test_get_returns_none_on_miss(monkeypatch):
    monkeypatch.setattr("src.cache.redis_cache.settings.cache_enabled", True)
    fake = MagicMock()
    fake.get.return_value = None
    set_client_for_tests(fake)
    assert get_cached_response("missing", "baseline") is None


def test_redis_down_degrades_gracefully(monkeypatch):
    monkeypatch.setattr("src.cache.redis_cache.settings.cache_enabled", True)
    monkeypatch.setattr("src.cache.redis_cache.settings.redis_url", "redis://invalid:1/0")
    reset_client_for_tests()

    with patch("redis.Redis.from_url", side_effect=ConnectionError("down")):
        assert get_cached_response("What is RAG?", "baseline") is None
        assert (
            set_cached_response(
                "What is RAG?",
                "baseline",
                AgentResponse(answer="x", mode="baseline"),
            )
            is False
        )


def test_runner_cache_hit_skips_dispatch(monkeypatch):
    monkeypatch.setattr("src.cache.redis_cache.settings.cache_enabled", True)

    store: dict[str, str] = {}
    fake = MagicMock()
    fake.get.side_effect = lambda k: store.get(k)
    fake.setex.side_effect = lambda k, ttl, v: store.__setitem__(k, v)
    set_client_for_tests(fake)

    from src.cache.redis_cache import set_cached_response as _set

    _set(
        "What is retrieval-augmented generation?",
        "baseline",
        AgentResponse(
            answer="Cached answer",
            mode="baseline",
            sources=["rag.pdf"],
            steps=["generate"],
        ),
    )

    dispatch = MagicMock()
    monkeypatch.setattr("src.runner._dispatch", dispatch)

    from src.runner import run_agent

    result = run_agent(
        "What is retrieval-augmented generation?",
        "baseline",
        use_memory=False,
    )
    assert result.answer == "Cached answer"
    assert "cache_hit" in result.steps
    dispatch.assert_not_called()


def test_flush_answer_cache_scans_and_deletes(monkeypatch):
    monkeypatch.setattr("src.cache.redis_cache.settings.redis_url", "redis://localhost:6379/0")
    fake = MagicMock()
    fake.scan.side_effect = [
        (1, ["rag:v1:baseline:a", "rag:v1:crag:b"]),
        (0, ["rag:v1:baseline:c"]),
    ]
    fake.delete.side_effect = lambda *keys: len(keys)
    set_client_for_tests(fake)

    deleted = flush_answer_cache()
    assert deleted == 3
    assert fake.delete.call_count == 2


def test_runner_skips_cache_when_memory_history(monkeypatch):
    monkeypatch.setattr("src.cache.redis_cache.settings.cache_enabled", True)

    fake = MagicMock()
    set_client_for_tests(fake)

    expected = AgentResponse(answer="Fresh", mode="baseline", sources=["s"])
    monkeypatch.setattr("src.runner._run_with_cost_tracking", lambda *a, **k: expected)
    monkeypatch.setattr("src.runner._attach_follow_ups", lambda *a, **k: [])
    monkeypatch.setattr("src.runner._maybe_quality_check", lambda *a, **k: True)

    from src.runner import run_agent

    result = run_agent(
        "What is RAG?",
        "baseline",
        chat_history=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
        use_memory=True,
    )
    assert result.answer == "Fresh"
    # Cost/rate-limit may touch Redis; answer-cache keys (rag:v1:*) must not.
    cache_gets = [
        c.args[0]
        for c in fake.get.call_args_list
        if c.args and str(c.args[0]).startswith("rag:v1:")
    ]
    cache_sets = [
        c.args[0]
        for c in fake.setex.call_args_list
        if c.args and str(c.args[0]).startswith("rag:v1:")
    ]
    assert cache_gets == []
    assert cache_sets == []
