"""Tests for FastAPI endpoints."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.config import settings
from src.schemas import AgentResponse


@pytest.fixture
def client():
    return TestClient(app)


def test_health_liveness(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


@patch("src.api.health.check_chroma", return_value={"status": "ok", "detail": "10 documents indexed"})
@patch("src.api.health.check_openai_configured", return_value={"status": "ok", "detail": "API key configured"})
@patch("src.api.health.check_data_directory", return_value={"status": "ok", "detail": "/data/chroma_db"})
@patch("src.api.health.check_redis", return_value={"status": "ok", "detail": "pong"})
@patch("src.api.health.check_groq_configured", return_value={"status": "skipped", "detail": "off"})
@patch("src.api.health.check_supabase_configured", return_value={"status": "skipped", "detail": "off"})
@patch("src.api.health.check_nvidia_configured", return_value={"status": "skipped", "detail": "off"})
def test_health_ready(
    _nvidia, _supabase, _groq, _redis, _mock_dir, _mock_openai, _mock_chroma, client
):
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert "checks" in body
    assert "redis" in body["checks"]


def test_metrics_endpoint(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "rag_requests_total" in resp.text or resp.headers["content-type"].startswith(
        "text/plain"
    )


def test_request_id_echoed(client):
    resp = client.get("/health", headers={"X-Request-ID": "test-rid-123"})
    assert resp.headers.get("X-Request-ID") == "test-rid-123"


@patch("src.api.server.run_agent")
def test_idempotency_key_returns_cached(mock_run, client, monkeypatch):
    monkeypatch.setattr(settings, "require_api_key", False)
    mock_run.return_value = AgentResponse(answer="once", mode="baseline", sources=[])

    store: dict[str, str] = {}
    fake = type("R", (), {})()

    def get(k):
        return store.get(k)

    def setex(k, ttl, v):
        store[k] = v

    fake.get = get
    fake.setex = setex

    from src.cache.redis_cache import set_client_for_tests, reset_client_for_tests

    set_client_for_tests(fake)
    try:
        headers = {"Idempotency-Key": "idem-1"}
        body = {"question": "What is RAG?", "mode": "baseline"}
        r1 = client.post("/query", json=body, headers=headers)
        r2 = client.post("/query", json=body, headers=headers)
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["answer"] == r2.json()["answer"]
        assert mock_run.call_count == 1
    finally:
        reset_client_for_tests()


@patch("src.api.server.run_agent")
def test_query_requires_api_key_when_enabled(mock_run, client, monkeypatch):
    monkeypatch.setattr(settings, "require_api_key", True)
    monkeypatch.setattr(settings, "api_key", "test-secret-key")
    mock_run.return_value = AgentResponse(answer="ok", mode="baseline")

    resp = client.post("/query", json={"question": "What is RAG?", "mode": "baseline"})
    assert resp.status_code == 401

    resp = client.post(
        "/query",
        json={"question": "What is RAG?", "mode": "baseline"},
        headers={"X-API-Key": "test-secret-key"},
    )
    assert resp.status_code == 200


@patch("src.api.server.run_agent")
def test_query_success_mocked(mock_run, client, monkeypatch):
    monkeypatch.setattr(settings, "require_api_key", False)
    mock_run.return_value = AgentResponse(
        answer="RAG combines retrieval with generation.",
        mode="baseline",
        sources=["doc1"],
        steps=["retrieve", "generate"],
        follow_ups=[
            "How does Self-RAG differ?",
            "When is CRAG useful?",
            "What is modular RAG?",
        ],
    )

    resp = client.post(
        "/query",
        json={"question": "What is RAG?", "mode": "baseline"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "RAG" in data["answer"]
    assert data["mode"] == "baseline"
    assert len(data["follow_ups"]) == 3


@patch("src.api.server.run_agent")
def test_query_passes_client_chat_history(mock_run, client, monkeypatch):
    monkeypatch.setattr(settings, "require_api_key", False)
    monkeypatch.setattr(settings, "memory_enabled", True)
    mock_run.return_value = AgentResponse(answer="CRAG grades and rewrites.", mode="agentic")

    history = [
        {"role": "user", "content": "What is Self-RAG?"},
        {"role": "assistant", "content": "Self-RAG grades its own retrievals."},
    ]
    resp = client.post(
        "/query",
        json={
            "question": "How does that compare to CRAG?",
            "mode": "agentic",
            "use_memory": True,
            "chat_history": history,
        },
    )
    assert resp.status_code == 200
    mock_run.assert_called_once()
    kwargs = mock_run.call_args.kwargs
    assert kwargs["use_memory"] is True
    assert kwargs["chat_history"] == history


@patch("src.api.server.run_agent")
def test_query_validation_error(mock_run, client, monkeypatch):
    monkeypatch.setattr(settings, "require_api_key", False)
    mock_run.side_effect = ValueError("Input validation failed: too short")

    resp = client.post("/query", json={"question": "What is RAG?", "mode": "baseline"})
    assert resp.status_code == 400


@patch("src.api.server.run_agent")
def test_query_rate_limit_returns_429(mock_run, client, monkeypatch):
    from src.guardrails import RateLimitError

    monkeypatch.setattr(settings, "require_api_key", False)
    mock_run.side_effect = RateLimitError("Rate limit exceeded")

    resp = client.post("/query", json={"question": "What is RAG?", "mode": "baseline"})
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


@patch("src.api.server.run_agent")
def test_per_client_rate_limit(mock_run, client, monkeypatch):
    from src.api import rate_limit
    from src.schemas import AgentResponse

    monkeypatch.setattr(settings, "require_api_key", False)
    monkeypatch.setattr(settings, "max_queries_per_minute_per_client", 2)
    rate_limit._history.clear()
    mock_run.return_value = AgentResponse(answer="ok", mode="baseline")

    for _ in range(2):
        resp = client.post("/query", json={"question": "What is RAG?", "mode": "baseline"})
        assert resp.status_code == 200

    resp = client.post("/query", json={"question": "What is RAG?", "mode": "baseline"})
    assert resp.status_code == 429
    rate_limit._history.clear()


def test_query_rejects_malformed_session_id(client, monkeypatch):
    monkeypatch.setattr(settings, "require_api_key", False)
    resp = client.post(
        "/query",
        json={"question": "What is RAG?", "mode": "baseline", "session_id": "x; DROP--"},
    )
    assert resp.status_code == 422


def test_query_rejects_empty_question(client, monkeypatch):
    monkeypatch.setattr(settings, "require_api_key", False)
    resp = client.post("/query", json={"question": "", "mode": "baseline"})
    assert resp.status_code == 422


def test_kb_search_and_system_lookup(client, monkeypatch):
    monkeypatch.setattr(settings, "require_api_key", False)
    search = client.get("/kb/v1/search", params={"q": "Who owns retriever-prod"})
    assert search.status_code == 200
    results = search.json()["results"]
    assert results
    assert any("platform-search" in r["body"] for r in results)

    system = client.get("/kb/v1/systems/retriever-prod")
    assert system.status_code == 200
    assert system.json()["owner"] == "platform-search"

    missing = client.get("/kb/v1/glossary/not-a-term")
    assert missing.status_code == 404


def test_mcp_http_initialize_and_call(client, monkeypatch):
    monkeypatch.setattr(settings, "require_api_key", False)
    init = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert init.status_code == 200
    assert init.json()["result"]["serverInfo"]["name"] == "agentic-rag-lab"

    called = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "search_lab_knowledge",
                "arguments": {"query": "exp-42 chunking"},
            },
        },
    )
    assert called.status_code == 200
    text = called.json()["result"]["content"][0]["text"]
    assert "12%" in text
