"""Node-level output gates — contain poison before it enters shared graph state.

Deterministic contract checks only (no LLM). Complements CRAG semantic grading
and infra circuit breakers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal
from collections.abc import Iterable

logger = logging.getLogger(__name__)

Severity = Literal["ok", "quarantine", "abort"]

# Machine-readable prefixes returned by tools (see src/tools/all_tools.py)
PREFIX_TOOL_ERROR = "[TOOL_ERROR]"
PREFIX_TOOL_EMPTY = "[TOOL_EMPTY]"
PREFIX_CIRCUIT_OPEN = "[CIRCUIT_OPEN]"

MAX_TOOL_FAILURES = 3
MIN_ANSWER_CHARS = 10

# Keep in sync with RouteType / VALID_STRATEGIES — duplicated here so this
# module stays free of LLM imports (tests + hot path).
ALLOWED_ROUTES = frozenset({"direct", "retrieve", "web_search"})
VALID_STRATEGIES = frozenset({"decompose", "multi_hop", "tools", "simple"})


@dataclass(frozen=True)
class GateResult:
    """Outcome of a node/tool contract check."""

    ok: bool
    severity: Severity
    code: str
    message: str

    @staticmethod
    def pass_(code: str = "ok", message: str = "") -> GateResult:
        return GateResult(ok=True, severity="ok", code=code, message=message)

    @staticmethod
    def quarantine(code: str, message: str) -> GateResult:
        return GateResult(ok=False, severity="quarantine", code=code, message=message)

    @staticmethod
    def abort(code: str, message: str) -> GateResult:
        return GateResult(ok=False, severity="abort", code=code, message=message)


def _record_metric(severity: Severity) -> None:
    if severity == "ok":
        return
    try:
        from src.api.metrics import record_node_gate

        record_node_gate(severity)
    except Exception:
        pass


def check_tool_result(tool_name: str, result: str | None) -> GateResult:
    """Classify a tool string result as ok / quarantine."""
    text = (result or "").strip()
    name = (tool_name or "").strip() or "unknown"

    if not text:
        return GateResult.quarantine(
            "tool_empty",
            f"{name} returned an empty result (not evidence)",
        )

    if text.startswith(PREFIX_CIRCUIT_OPEN):
        return GateResult.quarantine(
            "circuit_open",
            f"{name} unavailable (circuit open) — not evidence",
        )

    if text.startswith(PREFIX_TOOL_ERROR):
        return GateResult.quarantine(
            "tool_error",
            f"{name} failed — not evidence",
        )

    if text.startswith(PREFIX_TOOL_EMPTY):
        return GateResult.quarantine(
            "tool_empty",
            f"{name} found nothing — not evidence",
        )

    # Legacy / unknown-tool strings
    lower = text.lower()
    if "tool not found" in lower or text.startswith("Tool ") and "not found" in lower:
        return GateResult.quarantine("tool_missing", f"Unknown tool {name}")

    return GateResult.pass_(message=f"{name} ok")


def check_documents(docs: Iterable[Any] | None, *, required: bool = False) -> GateResult:
    """Structural check on a document list (not semantic relevance)."""
    items = list(docs or [])
    if items:
        return GateResult.pass_(message=f"{len(items)} documents")
    if required:
        return GateResult.abort("docs_required", "No documents available when evidence was required")
    return GateResult.quarantine("docs_empty", "No documents retrieved")


def check_answer(answer: str | None, *, required: bool = True) -> GateResult:
    """Reject empty/degenerate answers on the critical path."""
    text = (answer or "").strip()
    if len(text) >= MIN_ANSWER_CHARS:
        return GateResult.pass_(message="answer ok")
    if required:
        return GateResult.abort(
            "empty_answer",
            "Generator produced an empty or degenerate answer",
        )
    return GateResult.quarantine("empty_answer", "Answer empty (optional path)")


def check_route(route: str | None) -> GateResult:
    value = (route or "").strip()
    if value in ALLOWED_ROUTES:
        return GateResult.pass_(message=f"route={value}")
    return GateResult.abort(
        "invalid_route",
        f"Router returned invalid route {route!r}",
    )


def check_strategy(strategy: str | None) -> GateResult:
    value = (strategy or "").strip()
    if value in VALID_STRATEGIES:
        return GateResult.pass_(message=f"strategy={value}")
    return GateResult.abort(
        "invalid_strategy",
        f"Orchestrator returned invalid strategy {strategy!r}",
    )


def check_web_context(context: str | None) -> GateResult:
    """Web/search context must not be a tool failure sentinel."""
    return check_tool_result("web_search", context)


def quarantine_tool_message(gate: GateResult, tool_name: str) -> str:
    """Safe ToolMessage content — explicitly not usable as evidence."""
    return (
        f"[QUARANTINED] Tool '{tool_name}' result discarded ({gate.code}): {gate.message}. "
        "Do not treat this as retrieved evidence or factual web content."
    )


def abort_user_message(reason: str | None) -> str:
    detail = (reason or "a required step failed").strip()
    return (
        f"I couldn't complete this step because {detail}. "
        "Please try again or rephrase your question."
    )


def apply_gate(
    state_update: dict[str, Any],
    gate: GateResult,
    *,
    poison_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Merge a gate outcome into a graph state update dict.

    - ok: pass through
    - quarantine: clear poison_keys, append step
    - abort: set abort + abort_reason, clear poison_keys, append step
    """
    _record_metric(gate.severity)

    if gate.severity == "ok":
        return state_update

    update = dict(state_update)
    for key in poison_keys or []:
        if key == "documents" or key == "filtered_documents":
            update[key] = []
        elif key == "sources":
            update[key] = []
        elif key == "web_context":
            update[key] = ""
        elif key in update and isinstance(update[key], str):
            update[key] = ""

    steps = list(update.get("steps") or [])
    if gate.severity == "quarantine":
        steps.append(f"Node gate quarantine [{gate.code}]: {gate.message}")
        logger.info("node_gate_quarantine | code=%s | %s", gate.code, gate.message)
    else:
        update["abort"] = True
        update["abort_reason"] = gate.message
        steps.append(f"Node gate abort [{gate.code}]: {gate.message}")
        logger.warning("node_gate_abort | code=%s | %s", gate.code, gate.message)

    update["steps"] = steps
    return update
