"""LangSmith parent-span wiring (disabled in tests)."""

from __future__ import annotations

from src.observability import (
    agent_request_trace,
    graph_tracing_config,
    is_tracing_enabled,
    record_response_outputs,
    safe_graph_io,
    traced_execution,
)
from src.streaming import run_graph_streaming


def test_tracing_is_disabled_in_pytest():
    assert is_tracing_enabled() is False


def test_agent_request_trace_is_noop_when_disabled():
    with agent_request_trace(question="What is CRAG?", mode="canonical") as run:
        assert run is None


def test_traced_execution_is_noop_when_disabled():
    with traced_execution("custom"):
        pass


def test_graph_tracing_config_includes_run_name_and_tags():
    config = graph_tracing_config(
        "canonical_graph",
        metadata={"mode": "canonical"},
        recursion_limit=8,
    )
    assert config["run_name"] == "canonical_graph"
    assert "canonical_graph" in config["tags"]
    assert config["metadata"]["mode"] == "canonical"
    assert config["recursion_limit"] == 8


def test_safe_graph_io_extracts_canonical_fields():
    snapshot = safe_graph_io(
        {
            "canonical": {
                "original_question": "What is Self-RAG?",
                "mode": "canonical",
                "route": "retrieve",
                "strategy": "simple",
                "answer": "Self-RAG uses reflection tokens.",
                "grade_summary": "2/3 relevant",
            }
        }
    )
    assert snapshot["question"] == "What is Self-RAG?"
    assert snapshot["route"] == "retrieve"
    assert snapshot["grade_summary"] == "2/3 relevant"


def test_record_response_outputs_ignores_missing_run():
    record_response_outputs(None, object())


def test_run_graph_streaming_passes_run_name_config():
    seen: dict = {}

    class _Graph:
        def stream(self, initial, **kwargs):
            seen.update(kwargs)
            yield {"answer": "ok", "steps": ["n1"], "question": initial["question"]}

    result = run_graph_streaming(
        _Graph(),
        {"question": "q"},
        config=graph_tracing_config("canonical_graph"),
    )
    assert result["answer"] == "ok"
    assert seen["stream_mode"] == "values"
    assert seen["config"]["run_name"] == "canonical_graph"
