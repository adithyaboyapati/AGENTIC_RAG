"""Retrieval quality monitoring — proxy and offline metrics (Phase 8)."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from src.evaluation.production_observer import list_observations


@dataclass
class RetrievalMonitorReport:
    window_hours: float
    sample_count: int
    zero_evidence_rate: float
    retry_rate: float
    avg_evidence_count: float
    avg_citation_count: float
    proxy_recall: float | None = None
    proxy_mrr: float | None = None
    proxy_precision: float | None = None
    proxy_ndcg: float | None = None
    metrics_are_proxy: bool = True
    warnings: list[str] = field(default_factory=list)


def _safe_mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def build_retrieval_monitor_report(*, window_hours: float = 24.0) -> RetrievalMonitorReport:
    """Aggregate retrieval proxy signals from production observations."""
    rows = list_observations(since_hours=window_hours)
    if not rows:
        return RetrievalMonitorReport(
            window_hours=window_hours,
            sample_count=0,
            zero_evidence_rate=0.0,
            retry_rate=0.0,
            avg_evidence_count=0.0,
            avg_citation_count=0.0,
            warnings=["no_observations_in_window"],
        )

    zero_evidence = sum(1 for r in rows if r.get("zero_evidence"))
    retries = sum(1 for r in rows if int(r.get("retry_count") or 0) > 0)
    evidence_counts = [float(r.get("evidence_count") or 0) for r in rows]
    citation_counts = [float(r.get("citation_count") or 0) for r in rows]

    # Proxy: treat citation presence as recall proxy (NOT ground truth)
    proxy_hits = sum(1 for c in citation_counts if c > 0)
    proxy_recall = proxy_hits / len(rows) if rows else None

    report = RetrievalMonitorReport(
        window_hours=window_hours,
        sample_count=len(rows),
        zero_evidence_rate=round(zero_evidence / len(rows), 4),
        retry_rate=round(retries / len(rows), 4),
        avg_evidence_count=round(_safe_mean(evidence_counts), 2),
        avg_citation_count=round(_safe_mean(citation_counts), 2),
        proxy_recall=round(proxy_recall, 4) if proxy_recall is not None else None,
        proxy_mrr=None,
        proxy_precision=None,
        proxy_ndcg=None,
        metrics_are_proxy=True,
    )

    if report.zero_evidence_rate > 0.15:
        report.warnings.append("high_zero_evidence_rate")
    if report.retry_rate > 0.20:
        report.warnings.append("high_retry_rate")

    return report


def merge_offline_retrieval_scores(offline_summary: dict[str, Any]) -> dict[str, Any]:
    """Combine offline golden-set scores with production proxy report."""
    proxy = build_retrieval_monitor_report()
    return {
        "production_proxy": {
            "sample_count": proxy.sample_count,
            "zero_evidence_rate": proxy.zero_evidence_rate,
            "retry_rate": proxy.retry_rate,
            "proxy_recall": proxy.proxy_recall,
            "metrics_are_proxy": True,
            "warnings": proxy.warnings,
        },
        "offline_golden": {
            **offline_summary,
            "metrics_are_proxy": False,
        },
    }
