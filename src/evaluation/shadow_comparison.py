"""Compare legacy and canonical shadow executions."""

from __future__ import annotations

import hashlib
from typing import Any

from src.contracts.models import AgentResponse as CanonicalAgentResponse
from src.evaluation.shadow_models import (
    ComparisonStatus,
    DisagreementClass,
    PipelineMetrics,
    ShadowResult,
)
from src.schemas import AgentResponse as LegacyAgentResponse


def _answer_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _is_abstained_legacy(response: LegacyAgentResponse) -> bool:
    answer = (response.answer or "").strip().lower()
    if response.error_code:
        return True
    markers = (
        "don't have sufficient",
        "couldn't find relevant",
        "cannot answer",
        "insufficient evidence",
    )
    return any(marker in answer for marker in markers)


def _is_abstained_canonical(response: CanonicalAgentResponse) -> bool:
    if response.error_code:
        return True
    if response.response_status == "abstained":
        return True
    if response.verification and response.verification.abstained:
        return True
    return False


def metrics_from_legacy(
    response: LegacyAgentResponse,
    *,
    pipeline: str = "legacy",
    latency_ms: float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
) -> PipelineMetrics:
    citations = response.citations or []
    return PipelineMetrics(
        pipeline=pipeline,
        mode=response.mode,
        route=response.route,
        response_status="abstained" if _is_abstained_legacy(response) else "answered",
        citation_correctness=1.0 if citations else None,
        citation_completeness=len(citations) / max(1, len(response.sources or []))
        if response.sources
        else None,
        evidence_count=len(response.sources or []),
        useful_evidence_count=len(response.sources or []),
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=(input_tokens or 0) + (output_tokens or 0) if input_tokens or output_tokens else None,
        cost_usd=cost_usd,
        error_code=response.error_code,
        abstained=_is_abstained_legacy(response),
        answer_length=len(response.answer or ""),
        answer_hash=_answer_hash(response.answer or ""),
    )


def metrics_from_canonical(response: CanonicalAgentResponse) -> PipelineMetrics:
    verification = response.verification
    evidence_in_context = [e for e in response.evidence if e.included_in_context]
    trace_types = [event.event_type for event in response.trace]
    return PipelineMetrics(
        pipeline="canonical",
        mode=response.mode,
        route=response.route,
        strategy=response.strategy,
        strategy_source=(response.trace[0].metadata.get("decision_source") if response.trace else None),
        response_status=response.response_status,
        faithfulness=verification.faithfulness if verification else None,
        answer_relevance=verification.answer_relevance if verification else None,
        citation_correctness=verification.citation_correctness if verification else None,
        citation_completeness=verification.citation_completeness if verification else None,
        evidence_count=len(response.evidence),
        useful_evidence_count=len(evidence_in_context),
        verification_count=1 if verification else 0,
        web_search_count=sum(1 for node in (response.trace or ()) if node.node == "web_search"),
        latency_ms=response.latency_ms,
        error_code=response.error_code,
        abstained=_is_abstained_canonical(response),
        answer_length=len(response.answer or ""),
        answer_hash=_answer_hash(response.answer or ""),
    )


def _delta(canonical: float | None, legacy: float | None) -> float | None:
    if canonical is None or legacy is None:
        return None
    return round(canonical - legacy, 4)


def classify_disagreement(
    legacy: PipelineMetrics,
    canonical: PipelineMetrics,
) -> DisagreementClass:
    if legacy.error_code and canonical.error_code:
        return DisagreementClass.BOTH_WRONG
    if legacy.abstained and canonical.abstained:
        return DisagreementClass.BOTH_ABSTAINED
    if canonical.abstained and not legacy.abstained:
        return DisagreementClass.CANONICAL_ABSTAINED_LEGACY_ANSWERED
    if legacy.abstained and not canonical.abstained:
        return DisagreementClass.LEGACY_ABSTAINED_CANONICAL_ANSWERED

    legacy_score = _quality_score(legacy)
    canonical_score = _quality_score(canonical)
    if legacy_score is None or canonical_score is None:
        if (
            legacy.citation_correctness is not None
            and canonical.citation_correctness is not None
            and abs(legacy.citation_correctness - canonical.citation_correctness) >= 0.2
        ):
            return DisagreementClass.CITATION_DISAGREEMENT
        if abs(legacy.evidence_count - canonical.evidence_count) >= 2:
            return DisagreementClass.RETRIEVAL_DISAGREEMENT
        return DisagreementClass.INCONCLUSIVE

    if legacy_score >= 0.7 and canonical_score >= 0.7:
        return DisagreementClass.BOTH_CORRECT
    if legacy_score >= 0.7 and canonical_score < 0.5:
        return DisagreementClass.LEGACY_CORRECT_CANONICAL_WRONG
    if canonical_score >= 0.7 and legacy_score < 0.5:
        return DisagreementClass.CANONICAL_CORRECT_LEGACY_WRONG
    if legacy_score < 0.5 and canonical_score < 0.5:
        return DisagreementClass.BOTH_WRONG
    if (
        legacy.citation_correctness is not None
        and canonical.citation_correctness is not None
        and abs(legacy.citation_correctness - canonical.citation_correctness) >= 0.2
    ):
        return DisagreementClass.CITATION_DISAGREEMENT
    if abs(legacy.evidence_count - canonical.evidence_count) >= 2:
        return DisagreementClass.RETRIEVAL_DISAGREEMENT
    return DisagreementClass.INCONCLUSIVE


def _quality_score(metrics: PipelineMetrics) -> float | None:
    parts = [
        metrics.faithfulness,
        metrics.answer_relevance,
        metrics.citation_correctness,
    ]
    nums = [p for p in parts if p is not None]
    if not nums:
        if metrics.abstained:
            return 0.0
        if metrics.error_code:
            return 0.0
        return None
    return sum(nums) / len(nums)


def compare_pipelines(
    *,
    legacy_metrics: PipelineMetrics,
    canonical_metrics: PipelineMetrics,
) -> tuple[ComparisonStatus, DisagreementClass, dict[str, float | None], str | None]:
    disagreement = classify_disagreement(legacy_metrics, canonical_metrics)
    deltas = {
        "faithfulness": _delta(canonical_metrics.faithfulness, legacy_metrics.faithfulness),
        "answer_relevance": _delta(canonical_metrics.answer_relevance, legacy_metrics.answer_relevance),
        "citation_correctness": _delta(
            canonical_metrics.citation_correctness, legacy_metrics.citation_correctness
        ),
        "latency_ms": _delta(canonical_metrics.latency_ms, legacy_metrics.latency_ms),
        "cost_usd": _delta(canonical_metrics.cost_usd, legacy_metrics.cost_usd),
        "evidence_count": _delta(float(canonical_metrics.evidence_count), float(legacy_metrics.evidence_count)),
    }

    legacy_q = _quality_score(legacy_metrics)
    canonical_q = _quality_score(canonical_metrics)

    if legacy_metrics.error_code and not canonical_metrics.error_code:
        return ComparisonStatus.LEGACY_BETTER, disagreement, deltas, "legacy"
    if canonical_metrics.error_code and not legacy_metrics.error_code:
        return ComparisonStatus.CANONICAL_BETTER, disagreement, deltas, "canonical"
    if legacy_metrics.error_code and canonical_metrics.error_code:
        return ComparisonStatus.ERROR, disagreement, deltas, None

    if legacy_q is None or canonical_q is None:
        return ComparisonStatus.INCONCLUSIVE, disagreement, deltas, None

    margin = 0.05
    if canonical_q > legacy_q + margin:
        return ComparisonStatus.CANONICAL_BETTER, disagreement, deltas, "canonical"
    if legacy_q > canonical_q + margin:
        return ComparisonStatus.LEGACY_BETTER, disagreement, deltas, "legacy"
    return ComparisonStatus.EQUIVALENT, disagreement, deltas, None


def summarize_response(response: Any, *, include_answer: bool = False) -> dict[str, Any]:
    if isinstance(response, CanonicalAgentResponse):
        summary = {
            "mode": response.mode,
            "route": response.route,
            "strategy": response.strategy,
            "response_status": response.response_status,
            "error_code": response.error_code,
            "citation_count": len(response.citations),
            "evidence_count": len(response.evidence),
            "verification_outcome": (
                response.verification.outcome if response.verification else None
            ),
        }
        if include_answer:
            summary["answer"] = response.answer
        return summary

    summary = {
        "mode": response.mode,
        "route": response.route,
        "error_code": response.error_code,
        "source_count": len(response.sources or []),
        "citation_count": len(response.citations or []),
    }
    if include_answer:
        summary["answer"] = response.answer
    return summary


def enrich_shadow_result(result: ShadowResult) -> ShadowResult:
    status, disagreement, deltas, winner = compare_pipelines(
        legacy_metrics=result.legacy_metrics,
        canonical_metrics=result.canonical_metrics,
    )
    latency_delta = _delta(result.canonical_metrics.latency_ms, result.legacy_metrics.latency_ms)
    cost_delta = _delta(result.canonical_metrics.cost_usd, result.legacy_metrics.cost_usd)
    token_delta = None
    if result.canonical_metrics.total_tokens is not None and result.legacy_metrics.total_tokens is not None:
        token_delta = result.canonical_metrics.total_tokens - result.legacy_metrics.total_tokens
    return result.model_copy(
        update={
            "comparison_status": status,
            "disagreement_class": disagreement,
            "winner": winner,
            "quality_deltas": deltas,
            "latency_delta_ms": latency_delta,
            "cost_delta_usd": cost_delta,
            "token_delta": token_delta,
        }
    )
