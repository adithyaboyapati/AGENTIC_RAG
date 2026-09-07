"""Production quality dashboard aggregator (Phase 8)."""

from __future__ import annotations

from typing import Any

from src.evaluation.agentic_efficiency import build_agentic_efficiency_report
from src.evaluation.cost_attribution import build_cost_attribution
from src.evaluation.dataset_store import list_cases, list_eval_runs
from src.evaluation.drift_detection import detect_quality_drift
from src.evaluation.kb_monitoring import build_kb_quality_report
from src.evaluation.model_routing import model_quality_cost_summary
from src.evaluation.production_observer import list_observations
from src.evaluation.retrieval_drift import detect_retrieval_drift
from src.evaluation.retrieval_monitoring import build_retrieval_monitor_report
from src.evaluation.strategy_analytics import build_strategy_analytics
from src.evaluation.versioning import current_eval_manifest
from src.feedback.analytics import build_feedback_analytics


def build_quality_dashboard(*, window_hours: float = 24.0) -> dict[str, Any]:
    """Operator dashboard: retrieval, answer, citations, agentic, ops, cost, feedback."""
    observations = list_observations(since_hours=window_hours)
    latencies = sorted(float(r.get("latency_ms") or 0) for r in observations)
    p50 = latencies[len(latencies) // 2] if latencies else 0.0
    p95 = latencies[max(0, int(len(latencies) * 0.95) - 1)] if latencies else 0.0
    errors = sum(1 for r in observations if r.get("error_code"))

    retrieval = build_retrieval_monitor_report(window_hours=window_hours)
    strategy = build_strategy_analytics(window_hours=window_hours)
    efficiency = build_agentic_efficiency_report(window_hours=window_hours)
    cost = build_cost_attribution(window_hours=window_hours)
    feedback = build_feedback_analytics(window_hours=max(window_hours, 1.0))
    kb = build_kb_quality_report()
    quality_drift = detect_quality_drift(current_hours=window_hours)
    retrieval_drift = detect_retrieval_drift(current_hours=window_hours)

    verified = sum(
        1
        for r in observations
        if str(r.get("verification_status") or "").lower() in {"pass", "ok", "verified"}
    )
    abstentions = sum(1 for r in observations if str(r.get("response_status") or "") == "abstain")

    return {
        "manifest": current_eval_manifest().to_dict(),
        "window_hours": window_hours,
        "retrieval": {
            "proxy_recall": retrieval.proxy_recall,
            "zero_evidence_rate": retrieval.zero_evidence_rate,
            "retry_rate": retrieval.retry_rate,
            "avg_evidence_count": retrieval.avg_evidence_count,
            "metrics_are_proxy": retrieval.metrics_are_proxy,
            "drift_status": retrieval_drift.status.value,
            "drift_warnings": retrieval_drift.warnings,
        },
        "answer": {
            "verification_pass_rate_proxy": round(verified / len(observations), 4) if observations else None,
            "abstention_rate": round(abstentions / len(observations), 4) if observations else None,
            "metrics_are_proxy": True,
            "quality_drift_status": quality_drift.status.value,
        },
        "citations": {
            "avg_citation_count": retrieval.avg_citation_count,
            "metrics_are_proxy": True,
        },
        "agentic": {
            "strategy_distribution": {s.strategy: s.count for s in strategy.strategies},
            "unnecessary_strategy_llm_rate": efficiency.unnecessary_strategy_llm_rate,
            "ineffective_retry_rate": efficiency.ineffective_retry_rate,
            "unnecessary_multihop_rate": efficiency.unnecessary_multihop_rate,
            "strategies": [
                {
                    "strategy": s.strategy,
                    "count": s.count,
                    "avg_latency_ms": s.avg_latency_ms,
                    "avg_cost_usd": s.avg_cost_usd,
                    "error_rate": s.error_rate,
                    "verification_pass_rate": s.verification_pass_rate,
                }
                for s in strategy.strategies
            ],
        },
        "operations": {
            "sample_count": len(observations),
            "p50_latency_ms": round(p50, 2),
            "p95_latency_ms": round(p95, 2),
            "error_rate": round(errors / len(observations), 4) if observations else 0.0,
        },
        "cost": {
            "cost_per_request": cost.cost_per_request,
            "total_cost_usd": cost.total_cost_usd,
            "by_strategy": cost.by_strategy,
            "by_model": cost.by_model,
            "model_quality_cost": model_quality_cost_summary(observations),
        },
        "feedback": feedback,
        "knowledge_base": {
            "active_documents": kb.active_documents,
            "stale_documents": kb.stale_documents,
            "total_chunks": kb.total_chunks,
            "source_distribution": kb.source_distribution,
            "warnings": kb.warnings,
        },
        "evaluation": {
            "recent_runs": list_eval_runs(limit=5),
            "regression_cases": len(list_cases(status="regression")),
            "candidate_cases": len(list_cases(status="candidate")),
        },
    }
