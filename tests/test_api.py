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
def test_health_ready(_mock_dir, _mock_openai, _mock_chroma, client):
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert "checks" in body


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
    )

    resp = client.post(
        "/query",
        json={"question": "What is RAG?", "mode": "baseline"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "RAG" in data["answer"]
    assert data["mode"] == "baseline"


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
