"""Tests for production-safety controls.

Covers the failure modes that only appear under load or misconfiguration:
capacity backpressure, operational-endpoint auth, unbounded rate-limit state,
and startup config validation.
"""

import time
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.api import rate_limit
from src.api.server import _validate_production_config, app
from src.config import settings


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Operational endpoint auth
# ---------------------------------------------------------------------------


def test_metrics_requires_key_when_one_is_configured(client):
    with patch.object(settings, "api_key", "k" * 32):
        assert client.get("/metrics").status_code == 401
        ok = client.get("/metrics", headers={"X-API-Key": "k" * 32})
        assert ok.status_code == 200


def test_readiness_requires_key_when_one_is_configured(client):
    with patch.object(settings, "api_key", "k" * 32):
        assert client.get("/health/ready").status_code == 401


def test_liveness_is_always_public(client):
    """Load balancers must reach /health without credentials."""
    with patch.object(settings, "api_key", "k" * 32):
        assert client.get("/health").status_code == 200


def test_metrics_gate_can_be_disabled(client):
    with (
        patch.object(settings, "api_key", "k" * 32),
        patch.object(settings, "protect_metrics_endpoint", False),
    ):
        assert client.get("/metrics").status_code == 200


def test_metrics_open_in_dev_when_no_key_configured(client):
    """No key to check and not production — probes should not 503."""
    with patch.object(settings, "api_key", ""):
        assert client.get("/metrics").status_code == 200


# ---------------------------------------------------------------------------
# Production config validation
# ---------------------------------------------------------------------------


def test_production_rejects_wildcard_cors():
    with (
        patch.object(settings, "openai_api_key", "sk-test"),
        patch.object(settings, "api_key", "k" * 32),
        patch.object(settings, "cors_origins", "*"),
    ):
        with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
            _validate_production_config()


def test_production_rejects_short_api_key():
    with (
        patch.object(settings, "openai_api_key", "sk-test"),
        patch.object(settings, "api_key", "short"),
        patch.object(settings, "cors_origins", "https://app.example.com"),
    ):
        with pytest.raises(RuntimeError, match="32 characters"):
            _validate_production_config()


def test_production_rejects_multi_worker_with_memory_budgets():
    """Per-worker budgets would silently multiply every configured ceiling."""
    with (
        patch.object(settings, "openai_api_key", "sk-test"),
        patch.object(settings, "api_key", "k" * 32),
        patch.object(settings, "cors_origins", "https://app.example.com"),
        patch.object(settings, "api_workers", 4),
        patch.object(settings, "rate_limit_backend", "memory"),
    ):
        with pytest.raises(RuntimeError, match="rate/token budget"):
            _validate_production_config()


def test_production_accepts_a_safe_configuration():
    with (
        patch.object(settings, "openai_api_key", "sk-test"),
        patch.object(settings, "api_key", "k" * 32),
        patch.object(settings, "cors_origins", "https://app.example.com"),
        patch.object(settings, "api_workers", 4),
        patch.object(settings, "rate_limit_backend", "redis"),
    ):
        _validate_production_config()  # must not raise


# ---------------------------------------------------------------------------
# Rate-limit state is bounded
# ---------------------------------------------------------------------------


def test_rate_limit_history_prunes_idle_clients():
    """One dict entry per distinct IP seen since boot is an unbounded leak."""
    rate_limit._history.clear()
    rate_limit._last_prune = 0.0

    for i in range(50):
        rate_limit._enforce_memory(f"ip:10.0.0.{i}", limit=100)
    assert len(rate_limit._history) == 50

    # Jump past the window so every entry is stale, then force a sweep.
    rate_limit._last_prune = 0.0
    with patch.object(rate_limit, "_WINDOW_SECONDS", -1.0):
        rate_limit._prune_history(time.monotonic())
    assert rate_limit._history == {}


def test_rate_limit_still_rejects_over_limit_clients():
    rate_limit._history.clear()
    rate_limit._last_prune = time.monotonic()

    rate_limit._enforce_memory("ip:1.2.3.4", limit=2)
    rate_limit._enforce_memory("ip:1.2.3.4", limit=2)
    with pytest.raises(HTTPException) as exc:
        rate_limit._enforce_memory("ip:1.2.3.4", limit=2)
    assert exc.value.status_code == 429
    assert "Retry-After" in exc.value.headers


def test_rate_limit_does_not_record_rejected_requests():
    """A rejected call must not extend the window and starve recovery."""
    rate_limit._history.clear()
    rate_limit._last_prune = time.monotonic()

    rate_limit._enforce_memory("ip:5.6.7.8", limit=1)
    for _ in range(5):
        with pytest.raises(HTTPException):
            rate_limit._enforce_memory("ip:5.6.7.8", limit=1)
    assert len(rate_limit._history["ip:5.6.7.8"]) == 1


# ---------------------------------------------------------------------------
# Capacity backpressure
# ---------------------------------------------------------------------------


def test_query_returns_503_when_all_slots_busy(client):
    """Saturation must surface as fast 503 backpressure, not an unbounded queue."""
    with (
        patch.object(settings, "concurrency_acquire_timeout_seconds", 0.01),
        patch("src.api.server._query_semaphore") as sem,
    ):
        async def _never_acquire():
            import asyncio

            await asyncio.sleep(3600)

        sem.acquire.side_effect = _never_acquire
        resp = client.post("/query", json={"question": "What is RAG?", "mode": "baseline"})

    assert resp.status_code == 503
    assert resp.headers.get("Retry-After") == "5"
