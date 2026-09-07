"""Shadow runner: paired legacy + canonical evaluation without mutating production state."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import threading
import time
import uuid
from typing import Any

from src.config import settings
from src.evaluation.shadow_comparison import (
    enrich_shadow_result,
    metrics_from_canonical,
    metrics_from_legacy,
    summarize_response,
)
from src.evaluation.shadow_context import (
    canary_execution,
    replay_execution,
    shadow_execution,
)
from src.evaluation.shadow_fingerprint import (
    ShadowRequestContext,
    build_shadow_request_context,
    compute_input_fingerprint,
)
from src.evaluation.shadow_models import ExecutionMode, ShadowResult
from src.evaluation.shadow_sampling import SamplingDecision, SamplingOutcome, evaluate_sampling
from src.evaluation.shadow_storage import save_shadow_result
from src.retrieval.context import use_rbac_context
from src.schemas import AgentResponse as LegacyAgentResponse, RBACContext

logger = logging.getLogger(__name__)

_executor: concurrent.futures.ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()


def _get_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            workers = max(1, int(getattr(settings, "shadow_max_workers", 2)))
            _executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="shadow-eval",
            )
        return _executor


def eval_config_hash() -> str:
    payload = {
        "canonical_verification_llm_enabled": settings.canonical_verification_llm_enabled,
        "shadow_sampling_rate": getattr(settings, "shadow_sampling_rate", 0.0),
        "canary_percent": getattr(settings, "canary_percent", 0.0),
        "openai_model": settings.openai_model,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return digest[:16]


def _strategy_override(canonical_strategy: str | None) -> str | None:
    if not canonical_strategy or canonical_strategy == "auto":
        return None
    return canonical_strategy.replace("-", "_")


def run_legacy_pipeline(
    question: str,
    mode: str,
    *,
    rbac_context: RBACContext,
    chat_history: list[dict[str, str]] | None = None,
    use_memory: bool = False,
    skip_cache: bool = False,
) -> tuple[LegacyAgentResponse, dict[str, Any]]:
    """Run the authoritative legacy pipeline."""
    from src.runner import run_agent

    started = time.monotonic()
    with use_rbac_context(rbac_context):
        if skip_cache:
            with shadow_execution():
                response = run_agent(
                    question,
                    mode,
                    chat_history=chat_history,
                    use_memory=use_memory,
                    rbac_context=rbac_context,
                )
        else:
            response = run_agent(
                question,
                mode,
                chat_history=chat_history,
                use_memory=use_memory,
                rbac_context=rbac_context,
            )
    elapsed_ms = round((time.monotonic() - started) * 1000, 2)
    meta = {"latency_ms": elapsed_ms}
    return response, meta


def run_canonical_pipeline(
    question: str,
    *,
    rbac_context: RBACContext,
    canonical_strategy: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Run canonical graph in observational mode (no cache/memory side effects)."""
    from src.graph.canonical_graph import ask_canonical

    started = time.monotonic()
    with shadow_execution(), use_rbac_context(rbac_context):
        response = ask_canonical(
            question,
            rbac_context=rbac_context,
            force_strategy=_strategy_override(canonical_strategy),
        )
    elapsed_ms = round((time.monotonic() - started) * 1000, 2)
    if response.latency_ms is None:
        response = response.model_copy(update={"latency_ms": elapsed_ms})
    return response, {"latency_ms": elapsed_ms}


def run_paired_evaluation(
    *,
    question: str,
    legacy_mode: str,
    rbac_context: RBACContext,
    request_id: str | None = None,
    execution_mode: ExecutionMode = ExecutionMode.REPLAY,
    canonical_strategy: str | None = None,
    use_memory: bool = False,
    chat_history: list[dict[str, str]] | None = None,
    persist: bool = True,
    sampling: SamplingOutcome | None = None,
) -> ShadowResult:
    """Execute legacy + canonical on the same request and compare."""
    ctx = build_shadow_request_context(
        question=question,
        legacy_mode=legacy_mode,
        rbac_context=rbac_context,
        use_memory=use_memory,
        canonical_strategy=canonical_strategy,
        config_snapshot={"eval_config_hash": eval_config_hash()},
    )
    fingerprint = compute_input_fingerprint(ctx)
    req_id = request_id or f"shadow-{uuid.uuid4().hex[:12]}"
    errors: list[str] = []

    cm = replay_execution if execution_mode == ExecutionMode.REPLAY else shadow_execution
    with cm():
        legacy_response, legacy_meta = run_legacy_pipeline(
            ctx.sanitized_question,
            legacy_mode,
            rbac_context=rbac_context,
            chat_history=chat_history,
            use_memory=use_memory,
            skip_cache=True,
        )
        try:
            canonical_response, _canonical_meta = run_canonical_pipeline(
                ctx.sanitized_question,
                rbac_context=rbac_context,
                canonical_strategy=canonical_strategy,
            )
        except Exception as exc:
            errors.append(f"canonical_error:{type(exc).__name__}")
            from src.contracts.models import AgentResponse as CanonicalAgentResponse

            canonical_response = CanonicalAgentResponse(
                answer="",
                mode="canonical",
                error_code="canonical_shadow_failure",
                latency_ms=0.0,
                response_status="abstained",
            )

    include_answer = bool(getattr(settings, "shadow_store_raw_answers", False))
    legacy_metrics = metrics_from_legacy(
        legacy_response,
        latency_ms=legacy_meta.get("latency_ms"),
    )
    canonical_metrics = metrics_from_canonical(canonical_response)

    result = ShadowResult(
        request_id=req_id,
        tenant_id=ctx.tenant_id,
        input_fingerprint=fingerprint,
        execution_mode=execution_mode,
        legacy_mode=legacy_mode,
        canonical_strategy=canonical_strategy or "auto",
        legacy_metrics=legacy_metrics,
        canonical_metrics=canonical_metrics,
        legacy_response_summary=summarize_response(
            legacy_response, include_answer=include_answer
        ),
        canonical_response_summary=summarize_response(
            canonical_response, include_answer=include_answer
        ),
        sampling=(sampling.__dict__ if sampling else {}),
        eval_config_hash=eval_config_hash(),
        errors=tuple(errors),
    )
    result = enrich_shadow_result(result)
    if persist:
        save_shadow_result(result)
        _record_shadow_metrics(result)
    return result


def schedule_shadow_evaluation(
    *,
    question: str,
    legacy_mode: str,
    rbac_context: RBACContext,
    request_id: str,
    legacy_response: LegacyAgentResponse,
    legacy_meta: dict[str, Any] | None = None,
    canonical_strategy: str | None = None,
) -> None:
    """Fire-and-forget shadow canonical evaluation after legacy response is ready."""

    def _task() -> None:
        try:
            ctx = build_shadow_request_context(
                question=question,
                legacy_mode=legacy_mode,
                rbac_context=rbac_context,
                canonical_strategy=canonical_strategy,
                config_snapshot={"eval_config_hash": eval_config_hash()},
            )
            fingerprint = compute_input_fingerprint(ctx)
            sampling = evaluate_sampling(ctx, input_fingerprint=fingerprint)
            errors: list[str] = []
            try:
                canonical_response, _meta = run_canonical_pipeline(
                    ctx.sanitized_question,
                    rbac_context=rbac_context,
                    canonical_strategy=canonical_strategy,
                )
            except Exception as exc:
                logger.warning("Shadow canonical execution failed", exc_info=True)
                errors.append(f"canonical_error:{type(exc).__name__}")
                from src.contracts.models import AgentResponse as CanonicalAgentResponse

                canonical_response = CanonicalAgentResponse(
                    answer="",
                    mode="canonical",
                    error_code="canonical_shadow_failure",
                    latency_ms=0.0,
                    response_status="abstained",
                )

            include_answer = bool(getattr(settings, "shadow_store_raw_answers", False))
            result = ShadowResult(
                request_id=request_id,
                tenant_id=ctx.tenant_id,
                input_fingerprint=fingerprint,
                execution_mode=ExecutionMode.SHADOW,
                legacy_mode=legacy_mode,
                canonical_strategy=canonical_strategy or "auto",
                legacy_metrics=metrics_from_legacy(
                    legacy_response,
                    latency_ms=(legacy_meta or {}).get("latency_ms"),
                ),
                canonical_metrics=metrics_from_canonical(canonical_response),
                legacy_response_summary=summarize_response(
                    legacy_response, include_answer=include_answer
                ),
                canonical_response_summary=summarize_response(
                    canonical_response, include_answer=include_answer
                ),
                sampling=sampling.__dict__,
                eval_config_hash=eval_config_hash(),
                errors=tuple(errors),
            )
            result = enrich_shadow_result(result)
            save_shadow_result(result)
            _record_shadow_metrics(result)
        except Exception:
            logger.warning("Shadow evaluation task failed", exc_info=True)

    _get_executor().submit(_task)


def try_canonical_with_fallback(
    *,
    question: str,
    legacy_mode: str,
    rbac_context: RBACContext,
    chat_history: list[dict[str, str]] | None = None,
    use_memory: bool = False,
    canonical_strategy: str | None = None,
    request_id: str | None = None,
) -> tuple[LegacyAgentResponse, ShadowResult | None, str | None]:
    """Canary path: canonical first, legacy fallback on failure."""
    fallback_reason: str | None = None
    req_id = request_id or f"canary-{uuid.uuid4().hex[:12]}"
    try:
        with canary_execution(), use_rbac_context(rbac_context):
            canonical_response, _meta = run_canonical_pipeline(
                question,
                rbac_context=rbac_context,
                canonical_strategy=canonical_strategy,
            )
        if not _canonical_user_safe(canonical_response):
            fallback_reason = "canonical_verification_or_security_failed"
            raise ValueError(fallback_reason)

        from src.contracts.api_response import canonical_to_api_response

        legacy_like = canonical_to_api_response(
            canonical_response,
            display_mode="canonical",
        )
        legacy_like.tenant_id = rbac_context.tenant_id
        ctx = build_shadow_request_context(
            question=question,
            legacy_mode=legacy_mode,
            rbac_context=rbac_context,
            canonical_strategy=canonical_strategy,
            config_snapshot={"eval_config_hash": eval_config_hash()},
        )
        include_answer = bool(getattr(settings, "shadow_store_raw_answers", False))
        shadow = enrich_shadow_result(
            ShadowResult(
                request_id=req_id,
                tenant_id=ctx.tenant_id,
                input_fingerprint=compute_input_fingerprint(ctx),
                execution_mode=ExecutionMode.CANARY,
                legacy_mode=legacy_mode,
                canonical_strategy=canonical_strategy or "auto",
                legacy_metrics=metrics_from_legacy(legacy_like),
                canonical_metrics=metrics_from_canonical(canonical_response),
                legacy_response_summary=summarize_response(legacy_like, include_answer=include_answer),
                canonical_response_summary=summarize_response(
                    canonical_response, include_answer=include_answer
                ),
                eval_config_hash=eval_config_hash(),
            )
        )
        save_shadow_result(shadow)
        _record_shadow_metrics(shadow)
        return legacy_like, shadow, None
    except Exception as exc:
        fallback_reason = fallback_reason or f"canonical_failure:{type(exc).__name__}"
        logger.warning("Canary fallback triggered: %s", fallback_reason)
        if settings.legacy_fallback_enabled and settings.legacy_runtime_enabled:
            legacy_response, legacy_meta = run_legacy_pipeline(
                question,
                legacy_mode,
                rbac_context=rbac_context,
                chat_history=chat_history,
                use_memory=use_memory,
            )
        else:
            from src.contracts.api_response import safe_abstention_response

            legacy_response = safe_abstention_response(
                mode=legacy_mode,
                reason=fallback_reason,
                tenant_id=rbac_context.tenant_id,
            )
            legacy_meta = {"latency_ms": 0.0}
        from src.contracts.models import AgentResponse as CanonicalAgentResponse

        failed_canonical = CanonicalAgentResponse(
            answer="",
            mode="canonical",
            error_code="canonical_canary_failure",
            response_status="abstained",
        )
        ctx = build_shadow_request_context(
            question=question,
            legacy_mode=legacy_mode,
            rbac_context=rbac_context,
            canonical_strategy=canonical_strategy,
            config_snapshot={"eval_config_hash": eval_config_hash()},
        )
        include_answer = bool(getattr(settings, "shadow_store_raw_answers", False))
        shadow = enrich_shadow_result(
            ShadowResult(
                request_id=req_id,
                tenant_id=ctx.tenant_id,
                input_fingerprint=compute_input_fingerprint(ctx),
                execution_mode=ExecutionMode.CANARY,
                legacy_mode=legacy_mode,
                canonical_strategy=canonical_strategy or "auto",
                legacy_metrics=metrics_from_legacy(
                    legacy_response, latency_ms=legacy_meta.get("latency_ms")
                ),
                canonical_metrics=metrics_from_canonical(failed_canonical),
                legacy_response_summary=summarize_response(
                    legacy_response, include_answer=include_answer
                ),
                canonical_response_summary=summarize_response(
                    failed_canonical, include_answer=include_answer
                ),
                eval_config_hash=eval_config_hash(),
                errors=(fallback_reason,),
                fallback_reason=fallback_reason,
            )
        )
        save_shadow_result(shadow)
        _record_canonical_fallback(fallback_reason)
        return legacy_response, shadow, fallback_reason


def _canonical_user_safe(response: Any) -> bool:
    if response.error_code:
        return False
    if response.response_status == "abstained":
        return False
    if response.verification:
        outcome = response.verification.outcome
        if outcome == "FAIL":
            return False
        if outcome == "WARN" and not getattr(settings, "canary_allow_warn_responses", False):
            return False
    if not (response.answer or "").strip():
        return False
    return True


def should_shadow(context: ShadowRequestContext) -> SamplingOutcome:
    return evaluate_sampling(context)


def should_canary(context: ShadowRequestContext) -> bool:
    outcome = evaluate_sampling(context)
    return outcome.sampling_decision == SamplingDecision.CANARY


def _record_shadow_metrics(result: ShadowResult) -> None:
    try:
        from src.api.metrics import record_canary_comparison, record_shadow_comparison
        from src.evaluation.canary_rollout import get_rollout_state

        route = result.canonical_metrics.route or "unknown"
        strategy = result.canonical_metrics.strategy or "unknown"
        if result.execution_mode == ExecutionMode.CANARY:
            stage = get_rollout_state().canary_stage
            record_canary_comparison(
                comparison_status=result.comparison_status.value,
                stage=stage,
                route=route,
                strategy=strategy,
                latency_delta_s=(result.latency_delta_ms or 0.0) / 1000.0,
                cost_delta=result.cost_delta_usd or 0.0,
                token_delta=result.token_delta or 0,
            )
        else:
            record_shadow_comparison(
                comparison_status=result.comparison_status.value,
                route=route,
                strategy=strategy,
                latency_delta_s=(result.latency_delta_ms or 0.0) / 1000.0,
                cost_delta=result.cost_delta_usd or 0.0,
                token_delta=result.token_delta or 0,
            )
    except Exception:
        logger.debug("Shadow metric export skipped", exc_info=True)


def _record_canonical_fallback(reason: str) -> None:
    try:
        from src.api.metrics import record_canonical_fallback

        record_canonical_fallback(reason)
    except Exception:
        logger.debug("Canary fallback metric export skipped", exc_info=True)


def shutdown_shadow_executor() -> None:
    global _executor
    with _executor_lock:
        if _executor is not None:
            _executor.shutdown(wait=False, cancel_futures=True)
            _executor = None
