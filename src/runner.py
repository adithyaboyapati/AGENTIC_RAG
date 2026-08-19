"""Unified agent runner for CLI, API, and Streamlit."""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

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
    "consensus": "Phase 8 — Multi-Agent Consensus Debate",
}

MODE_DESCRIPTIONS = {
    "baseline": "Fixed pipeline: always retrieve → generate. No agentic decisions.",
    "router": "Agent routes each question to direct answer, retrieval, or web search.",
    "crag": "Grades retrieved docs, rewrites query on failure, falls back to web search.",
    "decompose": "Splits complex questions into sub-queries; retrieves in parallel.",
    "multi_hop": "Chains sequential retrievals where each hop builds on the last.",
    "tools": "Agent picks tools: retrieve docs, web search, or calculate. Uses function calling.",
    "agentic": "Full orchestrator: analyzes question → picks strategy (decompose/multi-hop/tools/simple) → grades → generates.",
    "consensus": "Multi-agent debate over retrieved chunks: Proposer → Challenger → Judge. Abstains when the sources cannot support the question.",
}

EXAMPLE_QUESTIONS = {
    "baseline": "What is retrieval-augmented generation?",
    "router": "Hello! What is corrective RAG?",
    "crag": "What is Self-RAG?",
    "decompose": "Compare naive RAG, advanced RAG, and modular RAG",
    "multi_hop": "What fallback does CRAG use when retrieval fails?",
    "tools": "What is 847 * 293 and what is modular RAG?",
    "agentic": "Compare RAG vs Agentic RAG; what is Self-RAG grading?",
    "consensus": "Compare the performance trade-offs between Naive RAG and Modular RAG",
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
    if mode == "consensus":
        if not settings.consensus_agent_enabled:
            raise ValueError(
                "Consensus mode is disabled (CONSENSUS_AGENT_ENABLED=false)"
            )
        from src.graph.consensus_graph import ask_consensus

        return ask_consensus(question)
    raise ValueError(f"Unknown mode: {mode}")


def _apply_post_guardrails(result: AgentResponse) -> AgentResponse:
    """Run output and privacy guardrails on every mode."""
    policy = get_privacy_policy()

    valid, violations = OutputGuardrails.validate(
        result.answer,
        sources=result.sources or [],
    )
    if not valid:
        for v in violations:
            if v.severity == "error":
                logger.warning("Output guardrail: %s", v.message)

    outcome = PrivacyGuard.apply_output(result.answer, policy)
    if outcome.findings:
        pii_count = sum(1 for f in outcome.findings if f.severity != "phi")
        phi_count = sum(1 for f in outcome.findings if f.severity == "phi")
        logger.warning(
            "Privacy: output contains %d PII/financial and %d PHI findings (mode=%s)",
            pii_count,
            phi_count,
            policy.output_mode.value,
        )

    if not outcome.allowed:
        raise ValueError(
            "Response blocked: output contains sensitive personal or health information"
        )

    result.answer = outcome.text
    return result


def _maybe_quality_check(question: str, result: AgentResponse) -> None:
    """Optionally run LLM-as-judge quality guardrails (extra cost; off by default)."""
    if not settings.quality_guardrails_enabled or not result.context_docs:
        return
    try:
        from src.evaluation.metrics import evaluate_metrics
        from src.guardrails import QualityGuardrails

        context = "\n---\n".join(result.context_docs)
        metrics = evaluate_metrics(question, result.answer, context)
        ok, violations = QualityGuardrails.validate(
            faithfulness=metrics.faithfulness,
            relevance=metrics.answer_relevance,
            context_precision=metrics.context_precision,
        )
        if not ok:
            for v in violations:
                logger.warning("Quality guardrail: %s", v.message)
    except Exception:
        logger.warning("Quality guardrail check failed", exc_info=True)


def run_agent(
    question: str,
    mode: str,
    chat_history: list[dict[str, str]] | None = None,
    use_memory: bool = True,
    rbac_context: Any | None = None,
) -> AgentResponse:
    """Dispatch a question to the selected agent mode with guardrails, privacy, and RBAC checks."""
    from src.cache.redis_cache import get_cached_response
    from src.schemas import RBACContext

    ctx = rbac_context if isinstance(rbac_context, RBACContext) else RBACContext()
    pre = _prepare_agent_run(question, mode, chat_history, use_memory, ctx)

    if pre.cacheable:
        cached = get_cached_response(pre.sanitized_question, mode, ctx)
        if cached is not None:
            return _apply_post_guardrails(cached)

    _consume_budget(pre.tracker)

    result = _run_with_cost_tracking(pre.effective_question, mode, pre.tracker)
    result = _apply_post_guardrails(result)
    result.tenant_id = ctx.tenant_id
    result = _finalize_agent_result(
        pre.sanitized_question, result, cacheable=pre.cacheable, rbac_context=ctx
    )
    return result


def _finalize_agent_result(
    question: str,
    result: AgentResponse,
    *,
    cacheable: bool,
    rbac_context: Any | None = None,
) -> AgentResponse:
    """Post-dispatch: quality/follow-ups/cache, with abort-aware handling."""
    from src.cache.redis_cache import set_cached_response

    if result.error_code:
        logger.warning(
            "node_gate_abort | mode=%s | code=%s | steps=%d",
            result.mode,
            result.error_code,
            len(result.steps or []),
        )
        # Do not invent follow-ups or cache poisoned/aborted outcomes
        result.follow_ups = []
        return result

    _maybe_quality_check(question, result)
    result.follow_ups = _attach_follow_ups(question, result)

    if cacheable:
        set_cached_response(question, result.mode, result, rbac_context=rbac_context)

    return result


def _attach_follow_ups(question: str, result: AgentResponse) -> list[str]:
    """Generate follow-ups from the user question + answer/context; never fail the request."""
    try:
        if result.mode == "consensus":
            from src.graph.consensus_graph import ABSTAIN_ANSWER

            score = result.consensus_score
            if result.answer == ABSTAIN_ANSWER or (score is not None and score < 0.4):
                return []

        from src.agents.followups import generate_follow_ups

        return generate_follow_ups(
            question=question,
            answer=result.answer,
            sources=result.sources or [],
        )
    except Exception:
        logger.warning("Follow-up attachment failed", exc_info=True)
        return []


def _estimate_tokens(text: str) -> int:
    """Best-effort token estimate when provider callbacks are unavailable."""
    if not text:
        return 0
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 4)


def _record_spend(
    mode: str,
    provider: str,
    prompt_tokens: int,
    completion_tokens: int,
    tracker,
) -> None:
    """Charge the budget, log, and export tokens/cost as Prometheus counters."""
    tracker.record_usage(prompt_tokens, completion_tokens)
    total = prompt_tokens + completion_tokens
    cost = tracker.calculate_cost(prompt_tokens, completion_tokens, provider=provider)

    if total:
        logger.info(
            "Token usage | mode=%s | provider=%s | prompt=%d | completion=%d | cost=$%.5f",
            mode,
            provider,
            prompt_tokens,
            completion_tokens,
            cost,
        )
        try:
            from src.api.metrics import record_token_usage

            record_token_usage(provider, prompt_tokens, completion_tokens, cost)
        except Exception:
            logger.debug("Token metric export skipped", exc_info=True)

    if total > settings.max_tokens_per_query:
        logger.warning(
            "Query exceeded per-query token limit (%d > %d)",
            total,
            settings.max_tokens_per_query,
        )


def _run_with_cost_tracking(question: str, mode: str, tracker) -> AgentResponse:
    """Dispatch while recording actual token usage against the budget."""
    from src.llm import get_llm_provider, reset_llm_provider

    reset_llm_provider()
    try:
        from langchain_community.callbacks.manager import get_openai_callback
    except ImportError:
        result = _dispatch(question, mode)
        provider = get_llm_provider()
        _record_spend(
            mode,
            provider,
            _estimate_tokens(question),
            _estimate_tokens(result.answer),
            tracker,
        )
        return result

    with get_openai_callback() as cb:
        result = _dispatch(question, mode)

    provider = get_llm_provider()
    prompt_tokens = cb.prompt_tokens
    completion_tokens = cb.completion_tokens

    # Groq (or other) fallback is invisible to the OpenAI callback — estimate.
    if provider == "groq" and not cb.total_tokens:
        prompt_tokens = _estimate_tokens(question)
        completion_tokens = _estimate_tokens(result.answer)

    _record_spend(mode, provider, prompt_tokens, completion_tokens, tracker)
    return result


@dataclass
class _Preflight:
    """Result of the shared pre-dispatch checks.

    ``sanitized_question`` is the user question after privacy redaction but
    *before* memory augmentation — it is what the cache is keyed on, so
    redaction never splits the cache and history never poisons it.
    ``effective_question`` is what actually reaches the model.
    """

    sanitized_question: str
    effective_question: str
    tracker: Any
    cacheable: bool
    rbac_context: Any = None


def _prepare_agent_run(
    question: str,
    mode: str,
    chat_history: list[dict[str, str]] | None,
    use_memory: bool,
    rbac_context: Any | None = None,
) -> _Preflight:
    """Shared pre-flight for run_agent / stream_agent.

    Order matters: privacy → input contract → cacheability. Budget consumption
    is deliberately *not* here — callers check the cache first via
    ``_consume_budget`` so a cache hit costs no quota. Per-client abuse is
    bounded at the HTTP layer (``enforce_client_rate_limit``), which is the
    right place for it.

    Raises ValueError on rejection.
    """
    from src.cache.redis_cache import should_use_cache
    from src.schemas import RBACContext

    ctx = rbac_context if isinstance(rbac_context, RBACContext) else RBACContext()
    policy = get_privacy_policy()

    privacy = PrivacyGuard.apply_input(question, policy)
    if not privacy.allowed:
        found_types = sorted({f.data_type.value for f in privacy.findings})
        raise ValueError(
            f"Input contains sensitive data: {', '.join(found_types)}. "
            "Please remove before proceeding."
        )
    if privacy.findings:
        logger.info(
            "Privacy: redacted %d finding(s) from input (mode=%s)",
            len(privacy.findings),
            policy.input_mode.value,
        )
    sanitized = privacy.text

    valid, violations = InputGuardrails.validate(sanitized)
    if not valid:
        error_msg = "; ".join(v.message for v in violations)
        raise ValueError(f"Input validation failed: {error_msg}")

    cacheable = should_use_cache(use_memory=use_memory, chat_history=chat_history)

    effective_question = sanitized
    if use_memory and chat_history:
        effective_question = augment_question_with_history(sanitized, chat_history)
        logger.debug(
            "Memory enabled — augmented question with %d prior messages",
            len(chat_history),
        )

    return _Preflight(
        sanitized_question=sanitized,
        effective_question=effective_question,
        tracker=get_cost_tracker(),
        cacheable=cacheable,
        rbac_context=ctx,
    )


def _consume_budget(tracker: Any) -> None:
    """Enforce process-wide rate + token budgets, then record the query.

    Called only when work will actually be dispatched (i.e. after a cache miss).
    """
    rate_ok, rate_violations = tracker.check_query_rate()
    if not rate_ok:
        raise RateLimitError(rate_violations[0].message)

    budget_ok, budget_violations = tracker.check_token_budget()
    if not budget_ok:
        raise RateLimitError(budget_violations[0].message)

    tracker.record_query()


def stream_agent(
    question: str,
    mode: str,
    chat_history: list[dict[str, str]] | None = None,
    use_memory: bool = True,
    cancelled: threading.Event | None = None,
    rbac_context: Any | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield progressive SSE-ready events: step / token / answer / follow_ups / sources / done / error.

    Runs the agent in a worker thread with a stream emitter so tokens and steps
    are forwarded as they are produced (not after the full pipeline finishes).

    ``cancelled`` lets the caller (the SSE endpoint) signal client disconnect.
    Worker threads cannot be killed, so the emitter checks the flag at each
    event boundary and unwinds the run instead of billing to completion.
    """
    from src.cache.redis_cache import get_cached_response
    from src.schemas import RBACContext
    from src.streaming import CancelledRun, use_emitter

    ctx = rbac_context if isinstance(rbac_context, RBACContext) else RBACContext()

    try:
        pre = _prepare_agent_run(question, mode, chat_history, use_memory, ctx)
    except ValueError as exc:
        yield {"type": "error", "message": str(exc)}
        return

    cacheable = pre.cacheable
    tracker = pre.tracker
    effective_question = pre.effective_question

    if cacheable:
        cached = get_cached_response(pre.sanitized_question, mode, ctx)
        if cached is not None:
            result = _apply_post_guardrails(cached)
            for step in result.steps or []:
                yield {"type": "step", "content": step}
            yield {"type": "answer", "content": result.answer}
            if result.follow_ups:
                yield {"type": "follow_ups", "content": result.follow_ups}
            citations = [c.to_dict() for c in (result.citations or [])]
            if citations or result.sources:
                yield {
                    "type": "sources",
                    "content": result.sources,
                    "citations": citations,
                }
            yield {"type": "done", "latency_ms": 0.0, "cached": True}
            return

    events: queue.Queue[dict[str, Any] | None] = queue.Queue()
    stop = cancelled if cancelled is not None else threading.Event()

    def emit(event: dict[str, Any]) -> None:
        # Event boundaries are the cancellation checkpoints: raising here
        # unwinds the graph out of the worker instead of running to completion
        # for a client that has already gone away.
        if stop.is_set():
            raise CancelledRun()
        events.put(event)

    def worker() -> None:
        try:
            _consume_budget(tracker)
            with use_emitter(emit):
                result = _run_with_cost_tracking(effective_question, mode, tracker)
            result = _apply_post_guardrails(result)
            result.tenant_id = ctx.tenant_id
            result = _finalize_agent_result(
                pre.sanitized_question, result, cacheable=cacheable, rbac_context=ctx
            )

            # Steps/tokens were already emitted during the run; send final payload
            emit({"type": "answer", "content": result.answer})
            if result.follow_ups:
                emit({"type": "follow_ups", "content": result.follow_ups})
            citations = [c.to_dict() for c in (result.citations or [])]
            if citations or result.sources:
                emit(
                    {
                        "type": "sources",
                        "content": result.sources or [],
                        "citations": citations,
                    }
                )
            done: dict[str, Any] = {
                "type": "done",
                "mode": result.mode,
                "route": result.route,
                "route_reason": result.route_reason,
                "steps": result.steps or [],
            }
            if result.error_code:
                done["error_code"] = result.error_code
            emit(done)
        except CancelledRun:
            logger.info("stream_agent cancelled by client | mode=%s", mode)
        except (RateLimitError, ValueError) as exc:
            events.put({"type": "error", "message": str(exc)})
        except Exception:
            logger.exception("stream_agent failed")
            events.put({"type": "error", "message": "Internal server error"})
        finally:
            events.put(None)

    thread = threading.Thread(target=worker, name=f"stream-agent-{mode}", daemon=True)
    thread.start()

    try:
        while True:
            item = events.get()
            if item is None:
                break
            yield item
    finally:
        # Generator closed early (client disconnect / timeout) — tell the worker.
        stop.set()

    thread.join(timeout=1.0)
