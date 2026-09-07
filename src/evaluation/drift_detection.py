"""Quality drift detection across production windows (Phase 8)."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from enum import Enum

from src.evaluation.production_observer import list_observations


class QualityDriftStatus(str, Enum):
    STABLE = "stable"
    WARNING = "warning"
    REGRESSION = "regression"


@dataclass
class QualityDriftReport:
    status: QualityDriftStatus
    current_window_hours: float
    baseline_window_hours: float
    metrics: dict[str, float] = field(default_factory=dict)
    deltas: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _quality_metrics(rows: list[dict]) -> dict[str, float]:
    if not rows:
        return {}
    n = len(rows)
    verified = sum(
        1 for r in rows if str(r.get("verification_status") or "").lower() in {"pass", "ok", "verified"}
    )
    errors = sum(1 for r in rows if r.get("error_code"))
    abstentions = sum(1 for r in rows if str(r.get("response_status") or "") == "abstain")
    costs = [float(r.get("cost_usd") or 0) for r in rows]
    latencies = [float(r.get("latency_ms") or 0) for r in rows]
    tokens = [int(r.get("input_tokens") or 0) + int(r.get("output_tokens") or 0) for r in rows]
    return {
        "verification_pass_rate_proxy": verified / n,
        "error_rate": errors / n,
        "abstention_rate": abstentions / n,
        "avg_cost_usd": statistics.mean(costs),
        "p95_latency_ms": sorted(latencies)[max(0, int(n * 0.95) - 1)] if latencies else 0.0,
        "avg_tokens": statistics.mean(tokens) if tokens else 0.0,
    }


def detect_quality_drift(
    *,
    current_hours: float = 24.0,
    baseline_hours: float = 168.0,
    min_samples: int = 20,
) -> QualityDriftReport:
    current_rows = list_observations(since_hours=current_hours)
    baseline_rows = list_observations(since_hours=baseline_hours)
    older = [r for r in baseline_rows if r not in current_rows[: len(current_rows)]]

    report = QualityDriftReport(
        status=QualityDriftStatus.STABLE,
        current_window_hours=current_hours,
        baseline_window_hours=baseline_hours,
        metrics=_quality_metrics(current_rows),
    )

    if len(current_rows) < min_samples or len(older or baseline_rows) < min_samples:
        report.warnings.append("insufficient_samples")
        return report

    base_metrics = _quality_metrics(older or baseline_rows)
    deltas = {
        k: round(report.metrics.get(k, 0.0) - base_metrics.get(k, 0.0), 4)
        for k in set(report.metrics) | set(base_metrics)
    }
    report.deltas = deltas

    if deltas.get("verification_pass_rate_proxy", 0) < -0.05:
        report.warnings.append("faithfulness_proxy_declining")
    if deltas.get("error_rate", 0) > 0.03:
        report.warnings.append("error_rate_increasing")
    if deltas.get("p95_latency_ms", 0) > 500:
        report.warnings.append("latency_regression")
    if deltas.get("avg_cost_usd", 0) > 0.002:
        report.warnings.append("cost_increasing")

    if any(w in report.warnings for w in ("faithfulness_proxy_declining", "error_rate_increasing")):
        report.status = QualityDriftStatus.REGRESSION
    elif report.warnings:
        report.status = QualityDriftStatus.WARNING

    return report
