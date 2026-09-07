"""Per-node timing helpers for the canonical graph."""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, TypeVar

from src.canonical_observability.canonical_metrics import record_node_latency, record_stage_latency

F = TypeVar("F", bound=Callable[..., Any])

_STAGE_BY_NODE = {
    "classify": "classify",
    "direct_answer": "generation",
    "web_search": "generation",
    "strategy_select": "strategy",
    "plan_retrieval": "retrieval",
    "retrieve": "retrieval",
    "grade": "grading",
    "rewrite": "retrieval",
    "reflect": "retrieval",
    "context": "context",
    "generate": "generation",
    "verify": "verification",
    "finalize": "finalize",
    "abort": "finalize",
    "web_fallback": "generation",
}


@contextmanager
def timed_node(node: str) -> Iterator[dict[str, Any]]:
    started_at = datetime.now(timezone.utc)
    start = time.monotonic()
    timing: dict[str, Any] = {"node": node, "started_at": started_at.isoformat()}
    try:
        yield timing
    finally:
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        completed_at = datetime.now(timezone.utc)
        timing["completed_at"] = completed_at.isoformat()
        timing["duration_ms"] = duration_ms
        record_node_latency(node, duration_ms / 1000.0)
        stage = _STAGE_BY_NODE.get(node)
        if stage:
            record_stage_latency(stage, duration_ms / 1000.0)


def wrap_canonical_node(node_name: str, fn: F) -> F:
    """Decorator adding timing metadata to trace events emitted by a node."""

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with timed_node(node_name) as timing:
            result = fn(*args, **kwargs)
        if isinstance(result, dict) and "canonical" in result:
            from src.graph.canonical_state import append_trace, read_graph_state, write_graph_state

            state = read_graph_state(result)
            state = append_trace(
                state,
                node=node_name,
                event_type="node_timing",
                message=f"{node_name} completed in {timing['duration_ms']}ms",
                metadata={
                    "started_at": timing["started_at"],
                    "completed_at": timing["completed_at"],
                    "duration_ms": timing["duration_ms"],
                },
            )
            return write_graph_state(state)
        return result

    return wrapper  # type: ignore[return-value]
