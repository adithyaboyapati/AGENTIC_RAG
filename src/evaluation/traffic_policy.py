"""Unified traffic policy for /query and /query/stream."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.config import settings
from src.evaluation.canary_rollout import (
    get_rollout_state,
    kill_canary,
)
from src.evaluation.canary_gates import evaluate_rollback_conditions
from src.evaluation.pipeline_version import PIPELINE_CANONICAL_V1, PIPELINE_LEGACY
from src.evaluation.preflight import run_preflight
from src.evaluation.shadow_fingerprint import (
    ShadowRequestContext,
    build_shadow_request_context,
    compute_input_fingerprint,
)
from src.evaluation.shadow_models import ExecutionMode, ShadowResult
from src.evaluation.shadow_runner import (
    run_legacy_pipeline,
    schedule_shadow_evaluation,
    try_canonical_with_fallback,
)
from src.evaluation.shadow_sampling import SamplingDecision, SamplingOutcome, evaluate_sampling
from src.schemas import AgentResponse, RBACContext

logger = logging.getLogger(__name__)


class TrafficPath(str, Enum):
    LEGACY = "legacy"
    CANARY = "canary"
    SHADOW_LEGACY = "shadow_legacy"
    FALLBACK = "fallback"


@dataclass(frozen=True)
class TrafficPolicyResolution:
    """Resolved policy decision before execution."""

    request_id: str
    input_fingerprint: str
    path: TrafficPath
    pipeline_version: str
    legacy_mode: str
    canonical_strategy: str | None
    sampling: SamplingOutcome
    canary_stage: str
    preflight_ok: bool
    block_reason: str | None = None


@dataclass
class TrafficPolicyResult:
    response: AgentResponse
    request_id: str
    execution_mode: str
    path: TrafficPath
    pipeline_version: str
    shadow_scheduled: bool = False
    canary_used: bool = False
    fallback_reason: str | None = None
    shadow_result: ShadowResult | None = None


def resolve_traffic_policy(
    *,
    question: str,
    mode: str,
    rbac_context: RBACContext,
    request_id: str,
    use_memory: bool = False,
    canonical_strategy: str | None = None,
) -> TrafficPolicyResolution:
    """Determine execution path before running legacy or canonical pipelines."""
    ctx = build_shadow_request_context(
        question=question,
        legacy_mode=mode,
        rbac_context=rbac_context,
        use_memory=use_memory,
        canonical_strategy=canonical_strategy or getattr(settings, "canary_strategy", "auto"),
    )
    fingerprint = compute_input_fingerprint(ctx)
    sampling = evaluate_sampling(ctx, input_fingerprint=fingerprint)
    rollout = get_rollout_state()
    strategy = canonical_strategy or getattr(settings, "canary_strategy", "auto")

    preflight = run_preflight(for_canary=False)
    if sampling.sampling_decision == SamplingDecision.CANARY:
        rollback = evaluate_rollback_conditions()
        if rollback.blocking_gates:
            logger.warning(
                "Canary auto-rollback triggered: %s",
                [g.gate_name for g in rollback.blocking_gates],
            )
            kill_canary()
            return TrafficPolicyResolution(
                request_id=request_id,
                input_fingerprint=fingerprint,
                path=TrafficPath.LEGACY,
                pipeline_version=PIPELINE_LEGACY,
                legacy_mode=mode,
                canonical_strategy=strategy,
                sampling=sampling,
                canary_stage=rollout.canary_stage,
                preflight_ok=False,
                block_reason="auto_rollback",
            )
        preflight = run_preflight(for_canary=True)
        if not preflight.canary_allowed:
            logger.warning("Canary blocked by preflight; falling back to legacy path")
            return TrafficPolicyResolution(
                request_id=request_id,
                input_fingerprint=fingerprint,
                path=TrafficPath.LEGACY,
                pipeline_version=PIPELINE_LEGACY,
                legacy_mode=mode,
                canonical_strategy=strategy,
                sampling=sampling,
                canary_stage=rollout.canary_stage,
                preflight_ok=False,
                block_reason="preflight_failed",
            )
        return TrafficPolicyResolution(
            request_id=request_id,
            input_fingerprint=fingerprint,
            path=TrafficPath.CANARY,
            pipeline_version=PIPELINE_CANONICAL_V1,
            legacy_mode=mode,
            canonical_strategy=strategy,
            sampling=sampling,
            canary_stage=rollout.canary_stage,
            preflight_ok=True,
        )

    if sampling.sampling_decision == SamplingDecision.SHADOW:
        return TrafficPolicyResolution(
            request_id=request_id,
            input_fingerprint=fingerprint,
            path=TrafficPath.SHADOW_LEGACY,
            pipeline_version=PIPELINE_LEGACY,
            legacy_mode=mode,
            canonical_strategy=strategy,
            sampling=sampling,
            canary_stage=rollout.canary_stage,
            preflight_ok=preflight.shadow_allowed,
        )

    return TrafficPolicyResolution(
        request_id=request_id,
        input_fingerprint=fingerprint,
        path=TrafficPath.LEGACY,
        pipeline_version=PIPELINE_LEGACY,
        legacy_mode=mode,
        canonical_strategy=strategy,
        sampling=sampling,
        canary_stage=rollout.canary_stage,
        preflight_ok=True,
    )


def execute_with_traffic_policy(
    *,
    question: str,
    mode: str,
    rbac_context: RBACContext,
    request_id: str,
    chat_history: list[dict[str, str]] | None = None,
    use_memory: bool = False,
    canonical_strategy: str | None = None,
    resolution: TrafficPolicyResolution | None = None,
) -> TrafficPolicyResult:
    """Execute sync query according to resolved traffic policy."""
    res = resolution or resolve_traffic_policy(
        question=question,
        mode=mode,
        rbac_context=rbac_context,
        request_id=request_id,
        use_memory=use_memory,
        canonical_strategy=canonical_strategy,
    )

    if res.path == TrafficPath.CANARY:
        return _execute_canary(res, question, rbac_context, chat_history, use_memory)

    started = time.monotonic()
    legacy_response, legacy_meta = run_legacy_pipeline(
        question,
        res.legacy_mode,
        rbac_context=rbac_context,
        chat_history=chat_history,
        use_memory=use_memory,
    )
    legacy_meta["latency_ms"] = round((time.monotonic() - started) * 1000, 2)

    shadow_scheduled = False
    if res.path == TrafficPath.SHADOW_LEGACY:
        schedule_shadow_evaluation(
            question=question,
            legacy_mode=res.legacy_mode,
            rbac_context=rbac_context,
            request_id=request_id,
            legacy_response=legacy_response,
            legacy_meta=legacy_meta,
            canonical_strategy=res.canonical_strategy,
        )
        shadow_scheduled = True
        _record_shadow_request("shadow")

    return TrafficPolicyResult(
        response=legacy_response,
        request_id=request_id,
        execution_mode=ExecutionMode.SHADOW.value if shadow_scheduled else "legacy",
        path=res.path,
        pipeline_version=res.pipeline_version,
        shadow_scheduled=shadow_scheduled,
    )


def _execute_canary(
    res: TrafficPolicyResolution,
    question: str,
    rbac_context: RBACContext,
    chat_history: list[dict[str, str]] | None,
    use_memory: bool,
) -> TrafficPolicyResult:
    _record_canary_request(res.canary_stage)
    legacy, shadow, fallback = try_canonical_with_fallback(
        question=question,
        legacy_mode=res.legacy_mode,
        rbac_context=rbac_context,
        chat_history=chat_history,
        use_memory=use_memory,
        canonical_strategy=res.canonical_strategy,
        request_id=res.request_id,
    )
    path = TrafficPath.CANARY if fallback is None else TrafficPath.FALLBACK
    if fallback:
        _record_canary_fallback(fallback, res.canary_stage)
        _record_canary_failure(res.canary_stage)
    else:
        _record_canary_success(res.canary_stage)
    return TrafficPolicyResult(
        response=legacy,
        request_id=res.request_id,
        execution_mode=ExecutionMode.CANARY.value,
        path=path,
        pipeline_version=PIPELINE_CANONICAL_V1 if fallback is None else PIPELINE_LEGACY,
        canary_used=fallback is None,
        fallback_reason=fallback,
        shadow_result=shadow,
    )


def iter_stream_with_traffic_policy(
    *,
    question: str,
    mode: str,
    rbac_context: RBACContext,
    request_id: str,
    chat_history: list[dict[str, str]] | None = None,
    use_memory: bool = False,
    cancelled: Any | None = None,
    canonical_strategy: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Stream SSE events using the same policy resolution as /query."""
    res = resolve_traffic_policy(
        question=question,
        mode=mode,
        rbac_context=rbac_context,
        request_id=request_id,
        use_memory=use_memory,
        canonical_strategy=canonical_strategy,
    )

    if res.path == TrafficPath.CANARY:
        yield from _stream_canary(res, question, mode, rbac_context, chat_history, use_memory)
        return

    from src.runner import stream_agent
    from src.schemas import AgentResponse, Citation

    legacy_response: AgentResponse | None = None
    legacy_meta: dict[str, Any] = {}
    started = time.monotonic()
    captured_answer = ""
    captured_sources: list[str] = []
    captured_citations: list[Citation] = []
    captured_mode = mode
    captured_route: str | None = None

    for event in stream_agent(
        question,
        mode,
        chat_history=chat_history,
        use_memory=use_memory,
        cancelled=cancelled,
        rbac_context=rbac_context,
    ):
        if event.get("type") == "answer":
            captured_answer = str(event.get("content") or "")
        elif event.get("type") == "sources":
            captured_sources = list(event.get("content") or [])
            raw_citations = event.get("citations") or []
            captured_citations = [
                Citation(**c) if isinstance(c, dict) else c for c in raw_citations
            ]
        elif event.get("type") == "done":
            legacy_meta["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
            captured_mode = str(event.get("mode") or mode)
            captured_route = event.get("route")
        yield event

    if res.path == TrafficPath.SHADOW_LEGACY:
        legacy_response = AgentResponse(
            answer=captured_answer,
            mode=captured_mode,
            sources=captured_sources,
            citations=captured_citations,
            route=captured_route,
        )
        schedule_shadow_evaluation(
            question=question,
            legacy_mode=mode,
            rbac_context=rbac_context,
            request_id=request_id,
            legacy_response=legacy_response,
            legacy_meta=legacy_meta,
            canonical_strategy=res.canonical_strategy,
        )
        _record_shadow_request("shadow")


def _stream_canary(
    res: TrafficPolicyResolution,
    question: str,
    mode: str,
    rbac_context: RBACContext,
    chat_history: list[dict[str, str]] | None,
    use_memory: bool,
) -> Iterator[dict[str, Any]]:
    _record_canary_request(res.canary_stage)
    start = time.monotonic()
    outcome = execute_with_traffic_policy(
        question=question,
        mode=mode,
        rbac_context=rbac_context,
        request_id=res.request_id,
        chat_history=chat_history,
        use_memory=use_memory,
        canonical_strategy=res.canonical_strategy,
        resolution=res,
    )
    result = outcome.response
    yield {"type": "step", "content": f"traffic_policy → {outcome.path.value}"}
    if outcome.fallback_reason:
        yield {"type": "step", "content": f"canary_fallback → {outcome.fallback_reason}"}
    yield {"type": "answer", "content": result.answer}
    if result.follow_ups:
        yield {"type": "follow_ups", "content": result.follow_ups}
    citations = [c.to_dict() for c in (result.citations or [])]
    if citations or result.sources:
        yield {"type": "sources", "content": result.sources or [], "citations": citations}
    yield {
        "type": "done",
        "mode": result.mode,
        "route": result.route,
        "latency_ms": round((time.monotonic() - start) * 1000, 2),
        "pipeline_version": outcome.pipeline_version,
        "canary_used": outcome.canary_used,
        "fallback_reason": outcome.fallback_reason,
    }


def _record_shadow_request(execution_mode: str) -> None:
    try:
        from src.api.metrics import record_shadow_request

        record_shadow_request(execution_mode)
    except Exception:
        pass


def _record_canary_request(stage: str) -> None:
    try:
        from src.api.metrics import record_canary_request

        record_canary_request(stage)
    except Exception:
        pass


def _record_canary_success(stage: str) -> None:
    try:
        from src.api.metrics import record_canary_success

        record_canary_success(stage)
    except Exception:
        pass


def _record_canary_fallback(reason: str, stage: str) -> None:
    try:
        from src.api.metrics import record_canary_fallback

        record_canary_fallback(reason, stage)
    except Exception:
        pass
