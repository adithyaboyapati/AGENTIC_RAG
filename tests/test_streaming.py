"""Tests for progressive streaming helpers and /query/stream SSE."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.config import settings
from src.schemas import Citation
from src.streaming import emit_step, emit_token, stream_text, use_emitter


@pytest.fixture
def client():
    return TestClient(app)


def test_stream_text_falls_back_to_invoke_without_emitter():
    chain = MagicMock()
    chain.invoke.return_value = "hello"
    assert stream_text(chain, {"q": "x"}) == "hello"
    chain.invoke.assert_called_once()
    chain.stream.assert_not_called()


def test_stream_text_emits_tokens_with_emitter():
    chain = MagicMock()
    chain.stream.return_value = iter(["Hel", "lo"])
    events: list[dict] = []

    with use_emitter(events.append):
        out = stream_text(chain, {"q": "x"})

    assert out == "Hello"
    assert [e for e in events if e["type"] == "token"] == [
        {"type": "token", "content": "Hel"},
        {"type": "token", "content": "lo"},
    ]


def test_emit_helpers_noop_without_emitter():
    emit_step("should not crash")
    emit_token("should not crash")


@patch("src.api.server.stream_agent")
def test_query_stream_sse_tokens_and_done(mock_stream, client, monkeypatch):
    monkeypatch.setattr(settings, "require_api_key", False)

    def fake_stream(*_args, **_kwargs):
        yield {"type": "step", "content": "Retrieved 2 chunks"}
        yield {"type": "token", "content": "Self"}
        yield {"type": "token", "content": "-RAG"}
        yield {"type": "answer", "content": "Self-RAG"}
        yield {"type": "follow_ups", "content": ["Q1?", "Q2?", "Q3?"]}
        yield {
            "type": "sources",
            "content": ["doc.pdf"],
            "citations": [
                Citation(
                    index=1,
                    chunk_id="c1",
                    source="doc.pdf",
                    snippet="snip",
                ).to_dict()
            ],
        }
        yield {"type": "done", "mode": "baseline", "steps": ["Retrieved 2 chunks"]}

    mock_stream.side_effect = fake_stream

    with client.stream(
        "POST",
        "/query/stream",
        json={"question": "What is Self-RAG?", "mode": "baseline"},
    ) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())

    assert '"type": "step"' in body or '"type":"step"' in body
    assert "Retrieved 2 chunks" in body
    assert '"type": "token"' in body or '"type":"token"' in body
    assert "Self" in body
    assert '"type": "done"' in body or '"type":"done"' in body
    assert "latency_ms" in body


@patch("src.api.server.stream_agent")
def test_query_stream_privacy_error_event(mock_stream, client, monkeypatch):
    monkeypatch.setattr(settings, "require_api_key", False)

    def fake_stream(*_args, **_kwargs):
        yield {"type": "error", "message": "Input contains sensitive data: email"}

    mock_stream.side_effect = fake_stream

    with client.stream(
        "POST",
        "/query/stream",
        json={"question": "My email is a@b.com", "mode": "baseline"},
    ) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())

    assert "sensitive data" in body
    assert '"type": "error"' in body or '"type":"error"' in body


# ---------------------------------------------------------------------------
# Cancellation — a client that goes away must stop the run, not keep billing
# ---------------------------------------------------------------------------


def test_cancelled_run_is_not_swallowed_by_node_error_handling():
    """Graph nodes catch broad `Exception`; cancellation must punch through."""
    from src.streaming import CancelledRun

    assert issubclass(CancelledRun, BaseException)
    assert not issubclass(CancelledRun, Exception)


def test_stream_text_does_not_catch_cancellation():
    from src.streaming import CancelledRun

    chain = MagicMock()
    chain.stream.side_effect = CancelledRun()

    with pytest.raises(CancelledRun):
        with use_emitter(lambda _e: None):
            stream_text(chain, {"q": "x"})
    chain.invoke.assert_not_called()


def test_stream_agent_stops_worker_when_consumer_closes():
    """Closing the generator early sets the cancel flag the worker checks."""
    import threading

    from src.runner import stream_agent

    cancelled = threading.Event()
    emitted = threading.Event()

    def fake_run(question, mode, tracker):
        from src.streaming import emit_token

        for _ in range(1000):
            emit_token("tok")
            emitted.set()
        raise AssertionError("worker ran to completion despite cancellation")

    with (
        patch("src.runner._run_with_cost_tracking", side_effect=fake_run),
        patch("src.runner._consume_budget"),
        patch.object(settings, "cache_enabled", False),
    ):
        stream = stream_agent("What is RAG?", "baseline", cancelled=cancelled)
        next(stream)  # pull one token so the worker is running
        stream.close()  # simulate client disconnect

    assert emitted.is_set()
    assert cancelled.is_set()


def test_stream_agent_propagates_external_cancel_flag():
    import threading

    from src.runner import stream_agent

    cancelled = threading.Event()
    cancelled.set()  # already gone before work starts

    with (
        patch("src.runner._run_with_cost_tracking") as run,
        patch("src.runner._consume_budget"),
        patch.object(settings, "cache_enabled", False),
    ):
        run.return_value = MagicMock(
            answer="hello there", mode="baseline", sources=[], citations=[],
            steps=[], follow_ups=[], error_code=None, route=None, route_reason=None,
        )
        events = list(stream_agent("What is RAG?", "baseline", cancelled=cancelled))

    # Nothing should be yielded: the first emit raises CancelledRun.
    assert events == []
