"""Unified agent runner for CLI, API, and Streamlit.

Phase 7: canonical-primary execution. Deprecated public mode names map to
canonical strategies for backward-compatible clients.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from src.config import settings
from src.contracts.api_response import canonical_to_api_response
from src.guardrails import (
    InputGuardrails,
    OutputGuardrails,
    RateLimitError,
    get_cost_tracker,
)
from src.memory.chat_memory import augment_question_with_history
from src.privacy import PrivacyGuard, get_privacy_policy
from src.observability import agent_request_trace, record_response_outputs
from src.retrieval.context import use_rbac_context
from src.runner_modes import (
    SOURCE_TOOLS_MODE,
    is_deprecated_mode,
    normalize_mode,
    record_deprecated_mode_usage,
    resolve_canonical_strategy,
)
from src.schemas import AgentResponse, RBACContext

logger = logging.getLogger(__name__)

CANONICAL_PIPELINE_VERSION = "v1"

# Shown in UI / GET /modes. Deprecated aliases still work on /query.
PUBLIC_MODE_LABELS = {
    "canonical": "Canonical Agentic RAG",
    "source_tools": "Tool-selected sources",
}

MODE_LABELS = {
    **PUBLIC_MODE_LABELS,
    "agentic": "Canonical Agentic RAG (deprecated alias)",
    "baseline": "Deprecated — maps to canonical",
    "router": "Deprecated — maps to canonical",
    "crag": "Deprecated — maps to canonical",
    "decompose": "Deprecated — maps to canonical",
    "multi_hop": "Deprecated — maps to canonical",
    "tools": "Deprecated — maps to canonical",
    "consensus": "Deprecated — maps to canonical",
}

MODE_DESCRIPTIONS = {
    "canonical": "Unified canonical pipeline with strategy selection, evidence, and verification.",
    "source_tools": "The LLM chooses among PDF, SQLite catalog, ops API, lab MCP, and calculator; source hits are CRAG-graded before answering.",
    "agentic": "Deprecated alias for the canonical pipeline.",
}

EXAMPLE_QUESTIONS = {
    "canonical": "Compare RAG vs Agentic RAG; what is Self-RAG grading?",
    "source_tools": "Who owns retriever-prod and what did experiment 42 conclude about chunking?",
    "agentic": "Compare RAG vs Agentic RAG; what is Self-RAG grading?",
}


def _dispatch(question: str, mode: str) -> AgentResponse:
    """Run canonical Agentic RAG, or the source-tools ReAct loop."""
    normalized = normalize_mode(mode)
    if normalized == SOURCE_TOOLS_MODE:
        from src.graph.source_tools_graph import ask_source_tools

        return ask_source_tools(question)

    from src.graph.canonical_graph import ask_canonical

    if is_deprecated_mode(normalized):
        record_deprecated_mode_usage(normalized)
        logger.info("Deprecated mode %s mapped to canonical strategy", normalized)

    strategy = resolve_canonical_strategy(normalized)
    canonical = ask_canonical(question, force_strategy=strategy)
    display_mode = "canonical" if settings.canonical_primary else normalized
    return canonical_to_api_response(canonical, display_mode=display_mode)


def _apply_post_guardrails(result: AgentResponse) -> AgentResponse:
    """Run output and privacy guardrails on every mode."""
    policy = get_privacy_policy()

    valid, violations = OutputGuardrails.validate(
        result.answer,
        sources=result.sources or [],
    )
    if not valid:
        error_msgs = [v.message for v in violations if v.severity == "error"]
        for v in violations:
            if v.severity == "error":
                logger.warning("Output guardrail: %s", v.message)
        if error_msgs:
            raise ValueError(
                "Response blocked: output failed safety checks ("
                + "; ".join(error_msgs)
                + ")"
            )

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


def _maybe_quality_check(question: str, result: AgentResponse) -> bool:
    """Optionally run LLM-as-judge quality guardrails (extra cost; off by default).

    Returns False when an error-severity quality check failed so the caller can
    skip caching an ungrounded answer. Never fails the user-facing request.
    """
    if not settings.quality_guardrails_enabled or not result.context_docs:
        return True
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
            errors = [v for v in violations if v.severity == "error"]
            if errors:
                note = errors[0].message
                if note not in (result.answer or ""):
                    result.answer = (
                        f"{(result.answer or '').rstrip()}\n\n"
                        f"_Note: {note}. Treat remaining claims as incompletely grounded._"
                    )
                return False
        return True
    except Exception:
        logger.warning("Quality guardrail check failed", exc_info=True)
        return True


def run_agent(
    question: str,
    mode: str,
    chat_history: list[dict[str, str]] | None = None,
    use_memory: bool = True,
    rbac_context: Any | None = None,
) -> AgentResponse:
    """Dispatch a question to the selected agent mode with guardrails, privacy, and RBAC checks."""
    from src.cache.redis_cache import get_cached_response
    from src.evaluation.shadow_context import is_observational_execution

    ctx = rbac_context if isinstance(rbac_context, RBACContext) else RBACContext()
    with use_rbac_context(ctx):
        pre = _prepare_agent_run(question, mode, chat_history, use_memory, ctx)
        with agent_request_trace(
            question=pre.sanitized_question,
            mode=mode,
            metadata={
                "tenant_id": ctx.tenant_id,
                "use_memory": use_memory,
            },
        ) as trace_run:
            if pre.cacheable and not is_observational_execution():
                cached = get_cached_response(pre.sanitized_question, mode, ctx)
                if cached is not None:
                    result = _apply_post_guardrails(cached)
                    record_response_outputs(trace_run, result, cached=True)
                    return result

            _consume_budget(pre.tracker, _estimate_tokens(pre.effective_question))

            result = _run_with_cost_tracking(pre.effective_question, mode, pre.tracker)
            result = _apply_post_guardrails(result)
            result.tenant_id = ctx.tenant_id
            result = _finalize_agent_result(
                pre.sanitized_question,
                result,
                cacheable=pre.cacheable and not is_observational_execution(),
                rbac_context=ctx,
            )
            _observe_production_request(
                question=pre.sanitized_question,
                mode=mode,
                result=result,
                rbac_context=ctx,
                tracker=pre.tracker,
            )
            record_response_outputs(trace_run, result, cached=False)
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

    quality_ok = _maybe_quality_check(question, result)
    result.follow_ups = _attach_follow_ups(question, result)

    if cacheable and quality_ok is not False:
        set_cached_response(question, result.mode, result, rbac_context=rbac_context)

    return result


def _observe_production_request(
    *,
    question: str,
    mode: str,
    result: AgentResponse,
    rbac_context: RBACContext,
    tracker: Any,
) -> None:
    """Record production telemetry for continuous evaluation (Phase 8)."""
    try:
        from src.evaluation.production_observer import observe_from_api_response
        from src.evaluation.shadow_context import is_observational_execution
        from src.llm import get_llm_provider
        from src.logging_config import get_request_id

        if is_observational_execution():
            return

        cost = 0.0
        input_tokens = 0
        output_tokens = 0
        if tracker is not None:
            input_tokens = int(getattr(tracker, "prompt_tokens", 0) or 0)
            output_tokens = int(getattr(tracker, "completion_tokens", 0) or 0)
            try:
                cost = float(
                    tracker.calculate_cost(input_tokens, output_tokens, provider=get_llm_provider())
                )
            except Exception:
                cost = 0.0

        observe_from_api_response(
            request_id=get_request_id(),
            tenant_id=rbac_context.tenant_id,
            result=result,
            latency_ms=float(getattr(result, "latency_ms", 0) or 0),
            cost_usd=cost,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model_id=get_llm_provider(),
            metadata={
                "strategy": result.route_reason,
                "verification_status": getattr(result, "verification_status", None),
                "strategy_decision_source": "unknown",
                "retry_count": 0,
                "evidence_count": len(result.context_docs or []),
                "llm_call_count": 0,
            },
        )
    except Exception:
        logger.debug("Production observation skipped", exc_info=True)


def _attach_follow_ups(question: str, result: AgentResponse) -> list[str]:
    """Generate follow-ups from the user question + answer/context; never fail the request."""
    try:
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


def _consume_budget(tracker: Any, estimated_tokens: int = 0) -> None:
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
    if estimated_tokens:
        tracker.record_usage(estimated_tokens, 0)


def _clip_text(text: str, limit: int = 4000) -> dict[str, Any]:
    value = text if isinstance(text, str) else str(text or "")
    if len(value) <= limit:
        return {"text": value, "truncated": False}
    return {
        "text": value[:limit],
        "truncated": True,
        "original_length": len(value),
    }


def build_pipeline_payload(
    *,
    question: str,
    mode: str,
    result: AgentResponse,
    sanitized_question: str,
    effective_question: str,
    latency_ms: float,
    cached: bool = False,
) -> dict[str, Any]:
    """Structured pipeline stages for the frontend debug panel."""
    citations = [c.to_dict() for c in (result.citations or [])]
    context_docs = list(result.context_docs or [])
    tool_steps = [
        step for step in (result.steps or []) if step.lower().startswith("tool")
    ]
    stages: list[dict[str, Any]] = [
        {
            "id": "query",
            "label": "User Query",
            "status": "complete",
            "data": {"question": question, "mode": mode, "sanitized": sanitized_question},
        },
        {
            "id": "processing",
            "label": "Query Processing",
            "status": "complete" if result.route else "skipped",
            "data": {
                "route": result.route,
                "route_reason": result.route_reason,
                "steps": list(result.steps or []),
            },
        },
        {
            "id": "tools",
            "label": "Tool Selection",
            "status": "complete" if tool_steps else "skipped",
            "data": {
                "calls": tool_steps,
                "route_reason": result.route_reason,
            },
        },
        {
            "id": "retrieval",
            "label": "Retrieval",
            "status": "complete" if citations or context_docs else "skipped",
            "data": {"sources": list(result.sources or [])},
        },
        {
            "id": "chunks",
            "label": "Retrieved Chunks",
            "status": "complete" if citations else "skipped",
            "data": {"count": len(citations), "citations": citations},
        },
        {
            "id": "rerank",
            "label": "Reranking",
            "status": "complete" if result.grade_summary else "skipped",
            "data": {"grade_summary": result.grade_summary},
        },
        {
            "id": "context",
            "label": "Context Construction",
            "status": "complete" if context_docs else "skipped",
            "data": {
                "doc_count": len(context_docs),
                "preview": _clip_text("\n---\n".join(context_docs[:3]), 2000),
            },
        },
        {
            "id": "generation",
            "label": "LLM Generation",
            "status": "complete" if result.answer else "skipped",
            "data": _clip_text(result.answer or "", 2000),
        },
        {
            "id": "answer",
            "label": "Final Answer",
            "status": "complete" if result.answer else "skipped",
            "data": {
                "answer": result.answer,
                "follow_ups": list(result.follow_ups or []),
                "latency_ms": latency_ms,
                "cached": cached,
            },
        },
    ]
    return {"type": "pipeline", "stages": stages}


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
    from src.evaluation.shadow_context import is_observational_execution
    from src.observability import agent_request_trace, record_response_outputs
    from src.streaming import CancelledRun, use_emitter

    ctx = rbac_context if isinstance(rbac_context, RBACContext) else RBACContext()

    try:
        pre = _prepare_agent_run(question, mode, chat_history, use_memory, ctx)
    except ValueError as exc:
        yield {"type": "error", "message": str(exc)}
        return

    cacheable = pre.cacheable and not is_observational_execution()
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
            yield build_pipeline_payload(
                question=question,
                mode=mode,
                result=result,
                sanitized_question=pre.sanitized_question,
                effective_question=pre.effective_question,
                latency_ms=0.0,
                cached=True,
            )
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
            with agent_request_trace(
                question=pre.sanitized_question,
                mode=mode,
                metadata={"tenant_id": ctx.tenant_id, "streaming": True},
            ) as trace_run:
                _consume_budget(tracker, _estimate_tokens(effective_question))
                with use_rbac_context(ctx), use_emitter(emit):
                    result = _run_with_cost_tracking(effective_question, mode, tracker)
                result = _apply_post_guardrails(result)
                result.tenant_id = ctx.tenant_id
                result = _finalize_agent_result(
                    pre.sanitized_question, result, cacheable=cacheable, rbac_context=ctx
                )
                record_response_outputs(trace_run, result, cached=False)

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
            emit(
                build_pipeline_payload(
                    question=question,
                    mode=mode,
                    result=result,
                    sanitized_question=pre.sanitized_question,
                    effective_question=pre.effective_question,
                    latency_ms=0.0,
                )
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
