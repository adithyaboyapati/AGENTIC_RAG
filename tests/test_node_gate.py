"""Node-level output gate (poison containment) tests."""

from __future__ import annotations

from src.resilience.node_gate import (
    PREFIX_CIRCUIT_OPEN,
    PREFIX_TOOL_EMPTY,
    PREFIX_TOOL_ERROR,
    GateResult,
    abort_user_message,
    apply_gate,
    check_answer,
    check_documents,
    check_route,
    check_strategy,
    check_tool_result,
    check_web_context,
    quarantine_tool_message,
)
def test_tool_sentinels_quarantine():
    assert check_tool_result("web_search", f"{PREFIX_CIRCUIT_OPEN} down").severity == "quarantine"
    assert check_tool_result("web_search", f"{PREFIX_TOOL_ERROR} boom").severity == "quarantine"
    assert check_tool_result("retrieve_docs", f"{PREFIX_TOOL_EMPTY} none").severity == "quarantine"
    assert check_tool_result("calculator", f"{PREFIX_TOOL_ERROR} bad").severity == "quarantine"


def test_valid_tool_results_pass():
    assert check_tool_result("calculator", "42").ok
    assert check_tool_result("retrieve_docs", "Some chunk about RAG").ok
    assert check_tool_result("web_search", "Latest news about AI").ok


def test_calculator_tool_uses_error_prefix():
    from src.tools.all_tools import calculator

    out = calculator.invoke({"expression": "not math"})
    assert str(out).startswith(PREFIX_TOOL_ERROR)
    assert check_tool_result("calculator", str(out)).severity == "quarantine"


def test_web_search_circuit_open_sentinel_is_quarantined():
    """Tool contract: circuit-open results use PREFIX_CIRCUIT_OPEN (see all_tools.web_search)."""
    out = f"{PREFIX_CIRCUIT_OPEN} Web search temporarily unavailable."
    gate = check_tool_result("web_search", out)
    assert gate.severity == "quarantine"
    msg = quarantine_tool_message(gate, "web_search")
    assert "[QUARANTINED]" in msg
    assert "not evidence" in msg.lower()


def test_invalid_route_aborts():
    gate = check_route("teleport")
    assert gate.severity == "abort"
    assert check_route("retrieve").ok
    assert check_route("direct").ok
    assert check_route("web_search").ok


def test_invalid_strategy_aborts():
    assert check_strategy("magic").severity == "abort"
    assert check_strategy("simple").ok
    assert check_strategy("decompose").ok


def test_empty_answer_aborts_when_required():
    assert check_answer("   ", required=True).severity == "abort"
    assert check_answer("A sufficiently long answer.", required=True).ok


def test_documents_empty_quarantine_unless_required():
    assert check_documents([], required=False).severity == "quarantine"
    assert check_documents([], required=True).severity == "abort"
    assert check_documents([object()], required=True).ok


def test_apply_gate_quarantine_strips_poison():
    update = apply_gate(
        {
            "sources": ["web search"],
            "web_context": f"{PREFIX_TOOL_ERROR} fail",
            "steps": ["prior"],
        },
        GateResult.quarantine("tool_error", "bad web"),
        poison_keys=["web_context", "sources"],
    )
    assert update["web_context"] == ""
    assert update["sources"] == []
    assert any("quarantine" in s.lower() for s in update["steps"])
    assert not update.get("abort")


def test_apply_gate_abort_sets_flags():
    update = apply_gate(
        {"answer": "x", "steps": []},
        GateResult.abort("empty_answer", "degenerate"),
        poison_keys=["answer"],
    )
    assert update["abort"] is True
    assert update["abort_reason"] == "degenerate"
    assert update["answer"] == ""
    assert "couldn't complete" in abort_user_message(update["abort_reason"]).lower()


def test_check_web_context_rejects_sentinels():
    assert check_web_context(f"{PREFIX_CIRCUIT_OPEN} x").severity == "quarantine"
    assert check_web_context("real search snippet about RAG").ok


def test_quarantined_web_not_treated_as_source_label():
    """Circuit-open web must not become a normal 'web search' source."""
    gate = check_tool_result(
        "web_search", f"{PREFIX_CIRCUIT_OPEN} Web search temporarily unavailable."
    )
    assert gate.severity == "quarantine"
    # Mimic tools_agent: only set used_web on healthy results
    used_web = gate.ok
    sources = ["web search"] if used_web else []
    assert sources == []


def test_retrieve_docs_empty_sentinel_is_quarantined():
    """Tool contract: empty retrieve uses PREFIX_TOOL_EMPTY (see all_tools.retrieve_docs)."""
    out = f"{PREFIX_TOOL_EMPTY} No documents found."
    assert check_tool_result("retrieve_docs", out).severity == "quarantine"
