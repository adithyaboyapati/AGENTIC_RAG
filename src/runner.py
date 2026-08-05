"""Unified agent runner for CLI and Streamlit."""

from __future__ import annotations

import logging

from src.config import settings
from src.guardrails import (
    InputGuardrails,
    OutputGuardrails,
    RateLimitError,
    get_cost_tracker,
)
from src.memory.chat_memory import augment_question_with_history
from src.privacy import PrivacyGuard, get_privacy_policy
from src.schemas import AgentResponse

logger = logging.getLogger(__name__)

MODE_LABELS = {
    "baseline": "Phase 1 — Baseline RAG",
    "router": "Phase 2 — Query Router",
    "crag": "Phase 3 — Corrective RAG",
    "decompose": "Phase 4 — Query Decomposition",
    "multi_hop": "Phase 5 — Multi-Hop Retrieval",
    "tools": "Phase 6 — Tool-Augmented Agent",
    "agentic": "Phase 7 — Full Agentic RAG",
}

MODE_DESCRIPTIONS = {
    "baseline": "Fixed pipeline: always retrieve → generate. No agentic decisions.",
    "router": "Agent routes each question to direct answer, retrieval, or web search.",
    "crag": "Grades retrieved docs, rewrites query on failure, falls back to web search.",
    "decompose": "Splits complex questions into sub-queries; retrieves in parallel.",
    "multi_hop": "Chains sequential retrievals where each hop builds on the last.",
    "tools": "Agent picks tools: retrieve docs, web search, or calculate. Uses function calling.",
    "agentic": "Full orchestrator: analyzes question → picks strategy (decompose/multi-hop/tools/simple) → grades → generates.",
}

EXAMPLE_QUESTIONS = {
    "baseline": "What is retrieval-augmented generation?",
    "router": "Hello! What is corrective RAG?",
    "crag": "What is Self-RAG?",
    "decompose": "Compare naive RAG, advanced RAG, and modular RAG",
    "multi_hop": "What fallback does CRAG use when retrieval fails?",
    "tools": "What is 847 * 293 and what is modular RAG?",
    "agentic": "Compare RAG vs Agentic RAG; what is Self-RAG grading?",
}


def _dispatch(question: str, mode: str) -> AgentResponse:
    """Run the selected agent mode (no guardrails)."""
    if mode == "baseline":
        from src.rag.baseline import ask_baseline

        return ask_baseline(question)
    if mode == "router":
        from src.graph.router_graph import ask_router

        return ask_router(question)
    if mode == "crag":
        from src.graph.crag_graph import ask_crag

        return ask_crag(question)
    if mode == "decompose":
        from src.graph.decompose_graph import ask_decompose

        return ask_decompose(question)
    if mode == "multi_hop":
        from src.graph.multi_hop_graph import ask_multi_hop

        return ask_multi_hop(question)
    if mode == "tools":
        from src.graph.tools_graph import ask_tools

        return ask_tools(question)
    if mode == "agentic":
        from src.graph.agent_graph import ask_agentic

        return ask_agentic(question)
    raise ValueError(f"Unknown mode: {mode}")


def _apply_post_guardrails(result: AgentResponse) -> AgentResponse:
    """Run output, privacy, and cost guardrails on every mode."""
    policy = get_privacy_policy()

    valid, violations = OutputGuardrails.validate(
        result.answer,
        sources=result.sources or [],
    )
    if not valid:
        for v in violations:
            if v.severity == "error":
                logger.warning("Output guardrail: %s", v.message)

    privacy_ok, pii_phi_findings = PrivacyGuard.check_output(result.answer, policy)
    if not privacy_ok:
        pii_count = sum(1 for f in pii_phi_findings if f.severity == "pii")
        phi_count = sum(1 for f in pii_phi_findings if f.severity == "phi")
        logger.warning("Privacy: output contains %d PII and %d PHI findings", pii_count, phi_count)

        if settings.block_output_pii:
            raise ValueError("Response blocked: output contains sensitive personal or health information")

        if settings.redact_output_pii:
            result.answer = PrivacyGuard.process_output(result.answer, policy)

    return result


def run_agent(
    question: str,
    mode: str,
    chat_history: list[dict[str, str]] | None = None,
    use_memory: bool = True,
) -> AgentResponse:
    """Dispatch a question to the selected agent mode with guardrails and privacy checks."""
    policy = get_privacy_policy()

    privacy_ok, pii_phi_findings = PrivacyGuard.check_input(question, policy)
    if not privacy_ok:
        found_types = sorted({f.data_type.value for f in pii_phi_findings})
        raise ValueError(
            f"Input contains sensitive data: {', '.join(found_types)}. Please remove before proceeding."
        )

    valid, violations = InputGuardrails.validate(question)
    if not valid:
        error_msg = "; ".join(v.message for v in violations)
        raise ValueError(f"Input validation failed: {error_msg}")

    tracker = get_cost_tracker()
    rate_ok, rate_violations = tracker.check_query_rate()
    if not rate_ok:
        raise RateLimitError(rate_violations[0].message)

    budget_ok, budget_violations = tracker.check_token_budget()
    if not budget_ok:
        raise RateLimitError(budget_violations[0].message)

    tracker.record_query()

    effective_question = question
    if use_memory and chat_history:
        effective_question = augment_question_with_history(question, chat_history)
        logger.debug("Memory enabled — augmented question with %d prior messages", len(chat_history))

    result = _run_with_cost_tracking(effective_question, mode, tracker)
    return _apply_post_guardrails(result)


def _run_with_cost_tracking(question: str, mode: str, tracker) -> AgentResponse:
    """Dispatch while recording actual token usage against the budget."""
    try:
        from langchain_community.callbacks.manager import get_openai_callback
    except ImportError:
        return _dispatch(question, mode)

    with get_openai_callback() as cb:
        result = _dispatch(question, mode)

    tracker.record_usage(cb.prompt_tokens, cb.completion_tokens)
    if cb.total_tokens:
        logger.info(
            "Token usage | mode=%s | prompt=%d | completion=%d | cost=$%.5f",
            mode,
            cb.prompt_tokens,
            cb.completion_tokens,
            tracker.calculate_cost(cb.prompt_tokens, cb.completion_tokens),
        )
    if cb.total_tokens > settings.max_tokens_per_query:
        logger.warning(
            "Query exceeded per-query token limit (%d > %d)",
            cb.total_tokens,
            settings.max_tokens_per_query,
        )
    return result
