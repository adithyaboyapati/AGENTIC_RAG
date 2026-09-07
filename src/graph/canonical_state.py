"""Canonical state initialization and LangGraph bridge helpers."""

from __future__ import annotations

import operator
import time
from typing import Annotated, Any, TypedDict

from src.contracts.models import TraceEvent
from src.contracts.state import CanonicalAgentState
from src.contracts.validation import validate_canonical_agent_state
from src.schemas import RBACContext


class CanonicalGraphState(TypedDict, total=False):
    """LangGraph carrier for CanonicalAgentState (serialized)."""

    canonical: dict[str, Any]
    trace_delta: Annotated[list[dict[str, Any]], operator.add]


def init_canonical_state(
    question: str,
    *,
    rbac_context: RBACContext | None = None,
    mode: str = "canonical",
    strategy_override: str | None = None,
) -> CanonicalAgentState:
    """Initialize a fully-populated canonical state and validate it."""
    rbac = rbac_context or RBACContext()
    state = CanonicalAgentState(
        original_question=question.strip(),
        rbac_context=rbac,
        mode=mode,
        search_query=question.strip(),
        strategy=strategy_override or "simple",
        trace=(
            TraceEvent(
                node="init",
                event_type="request_started",
                message="Canonical request initialized",
                metadata={"mode": mode, "tenant_id": rbac.tenant_id},
            ),
        ),
    )
    validate_canonical_agent_state(state)
    return state


def serialize_state(state: CanonicalAgentState) -> dict[str, Any]:
    return state.model_dump(mode="json")


def deserialize_state(data: dict[str, Any]) -> CanonicalAgentState:
    return CanonicalAgentState.model_validate(data)


def merge_state(state: CanonicalAgentState, **updates: Any) -> CanonicalAgentState:
    """Return a new state; never mutate original_question or rbac_context."""
    blocked = {"original_question", "rbac_context"}
    for key in blocked:
        if key in updates and updates[key] != getattr(state, key):
            raise ValueError(f"{key} is immutable during a canonical run")
    new_state = state.model_copy(update=updates)
    validate_canonical_agent_state(new_state)
    return new_state


def append_trace(
    state: CanonicalAgentState,
    *,
    node: str,
    event_type: str,
    message: str = "",
    metadata: dict[str, Any] | None = None,
) -> CanonicalAgentState:
    event = TraceEvent(
        node=node,
        event_type=event_type,
        message=message,
        metadata=metadata or {},
    )
    return merge_state(state, trace=state.trace + (event,))


def graph_input(state: CanonicalAgentState) -> CanonicalGraphState:
    return {"canonical": serialize_state(state), "trace_delta": []}


def read_graph_state(raw: CanonicalGraphState) -> CanonicalAgentState:
    return deserialize_state(raw["canonical"])


def write_graph_state(state: CanonicalAgentState) -> CanonicalGraphState:
    trace_events = [
        event.model_dump(mode="json")
        for event in state.trace[-1:]
    ] if state.trace else []
    return {
        "canonical": serialize_state(state),
        "trace_delta": trace_events,
    }


class CanonicalTimer:
    """Track wall-clock latency for canonical runs."""

    def __init__(self) -> None:
        self._start = time.monotonic()

    def elapsed_ms(self) -> float:
        return round((time.monotonic() - self._start) * 1000, 2)
