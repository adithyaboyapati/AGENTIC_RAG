"""Retrieval drift detection (Phase 8)."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.evaluation.production_observer import list_observations


class DriftStatus(str, Enum):
    STABLE = "stable"
    WARNING = "warning"
    REGRESSION = "regression"


@dataclass
class RetrievalDriftReport:
    status: DriftStatus
    current_window_hours: float
    baseline_window_hours: float
    current_sample_count: int
    baseline_sample_count: int
    deltas: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _window_stats(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {}
    n = len(rows)
    return {
        "zero_evidence_rate": sum(1 for r in rows if r.get("zero_evidence")) / n,
        "retry_rate": sum(1 for r in rows if int(r.get("retry_count") or 0) > 0) / n,
        "avg_evidence_count": statistics.mean(float(r.get("evidence_count") or 0) for r in rows),
        "avg_citation_count": statistics.mean(float(r.get("citation_count") or 0) for r in rows),
    }


def detect_retrieval_drift(
    *,
    current_hours: float = 24.0,
    baseline_hours: float = 168.0,
    min_samples: int = 20,
) -> RetrievalDriftReport:
    """Compare recent retrieval proxy metrics against a longer baseline."""
    now_rows = list_observations(since_hours=current_hours)
    all_rows = list_observations(since_hours=baseline_hours)
    baseline_cutoff_rows = [r for r in all_rows if r not in now_rows[: len(now_rows)]]

    current_stats = _window_stats(now_rows)
    baseline_stats = _window_stats(baseline_cutoff_rows or all_rows)

    report = RetrievalDriftReport(
        status=DriftStatus.STABLE,
        current_window_hours=current_hours,
        baseline_window_hours=baseline_hours,
        current_sample_count=len(now_rows),
        baseline_sample_count=len(baseline_cutoff_rows or all_rows),
    )

    if len(now_rows) < min_samples or report.baseline_sample_count < min_samples:
        report.warnings.append("insufficient_samples_for_drift_detection")
        return report

    deltas: dict[str, float] = {}
    for key in ("zero_evidence_rate", "retry_rate", "avg_evidence_count", "avg_citation_count"):
        cur = current_stats.get(key, 0.0)
        base = baseline_stats.get(key, 0.0)
        deltas[key] = round(cur - base, 4)
    report.deltas = deltas

    if deltas.get("zero_evidence_rate", 0) > 0.05:
        report.warnings.append("zero_evidence_rate_increased")
    if deltas.get("retry_rate", 0) > 0.08:
        report.warnings.append("retry_rate_increased")
    if deltas.get("avg_evidence_count", 0) < -0.5:
        report.warnings.append("evidence_count_declining")
    if deltas.get("avg_citation_count", 0) < -0.3:
        report.warnings.append("citation_count_declining")

    if len(report.warnings) >= 2:
        report.status = DriftStatus.REGRESSION
    elif report.warnings:
        report.status = DriftStatus.WARNING

    return report
