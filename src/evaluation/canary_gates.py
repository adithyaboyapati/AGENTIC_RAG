"""Formal promotion and rollback gates for canary rollout."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.config import settings
from src.evaluation.canary_rollout import stage_hold_satisfied
from src.evaluation.preflight import run_preflight
from src.evaluation.shadow_storage import list_shadow_results


class GateRecommendation(str, Enum):
    NOT_READY = "NOT_READY"
    READY_FOR_CANARY = "READY_FOR_CANARY"
    READY_FOR_FULL_CUTOVER = "READY_FOR_FULL_CUTOVER"


@dataclass(frozen=True)
class CanaryGateResult:
    gate_name: str
    passed: bool
    actual_value: str | float | int | None
    required_value: str | float | int | None
    sample_count: int
    reason: str


@dataclass
class CanaryGateEvaluation:
    eligible: bool
    blocking_gates: list[CanaryGateResult] = field(default_factory=list)
    warnings: list[CanaryGateResult] = field(default_factory=list)
    passed_gates: list[CanaryGateResult] = field(default_factory=list)
    recommendation: GateRecommendation = GateRecommendation.NOT_READY
    sample_count: int = 0


def _paired_rows(mode_filter: str | None = None) -> list[dict[str, Any]]:
    rows = list_shadow_results(limit=5000)
    if mode_filter:
        return [r for r in rows if r.get("execution_mode") == mode_filter]
    return rows


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, int(round((pct / 100.0) * (len(ordered) - 1))))
    return round(ordered[idx], 4)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _gate(
    name: str,
    passed: bool,
    actual: Any,
    required: Any,
    sample_count: int,
    reason: str,
) -> CanaryGateResult:
    return CanaryGateResult(
        gate_name=name,
        passed=passed,
        actual_value=actual,
        required_value=required,
        sample_count=sample_count,
        reason=reason,
    )


def evaluate_shadow_evidence_gate(*, min_samples: int | None = None) -> CanaryGateEvaluation:
    """Gate shadow evidence before user-visible canary."""
    required = min_samples or max(30, int(getattr(settings, "shadow_minimum_samples", 30)))
    rows = _paired_rows()
    sample_count = len(rows)
    gates: list[CanaryGateResult] = []

    gates.append(
        _gate(
            "shadow_minimum_samples",
            sample_count >= required,
            sample_count,
            required,
            sample_count,
            f"Need >={required} paired shadow records",
        )
    )

    security_failures = sum(
        1 for r in rows if "security" in str(r.get("errors", [])).lower()
    )
    gates.append(
        _gate(
            "shadow_security_clean",
            security_failures == 0,
            security_failures,
            0,
            sample_count,
            "No security failures in shadow dataset",
        )
    )

    canonical_errors = sum(
        1 for r in rows if (r.get("canonical_metrics") or {}).get("error_code")
    )
    error_rate = (canonical_errors / sample_count) if sample_count else 1.0
    max_error = float(getattr(settings, "canary_max_error_rate", 0.05))
    gates.append(
        _gate(
            "shadow_canonical_error_rate",
            sample_count == 0 or error_rate <= max_error,
            round(error_rate, 4),
            max_error,
            sample_count,
            "Canonical shadow error rate within tolerance",
        )
    )

    faith_values = [
        float((r.get("canonical_metrics") or {}).get("faithfulness"))
        for r in rows
        if (r.get("canonical_metrics") or {}).get("faithfulness") is not None
    ]
    faith_mean = _mean(faith_values)
    gates.append(
        _gate(
            "shadow_faithfulness_measured",
            faith_mean is not None,
            faith_mean,
            "measured",
            sample_count,
            "Faithfulness metrics available from shadow runs",
        )
    )

    blocking = [g for g in gates if not g.passed]
    return CanaryGateEvaluation(
        eligible=not blocking,
        blocking_gates=blocking,
        passed_gates=[g for g in gates if g.passed],
        recommendation=(
            GateRecommendation.READY_FOR_CANARY
            if not blocking
            else GateRecommendation.NOT_READY
        ),
        sample_count=sample_count,
    )


def evaluate_canary_promotion_gates(*, target_stage: str | None = None) -> CanaryGateEvaluation:
    """Evaluate whether promotion to the next canary stage is supported by evidence."""
    rows = _paired_rows("canary")
    sample_count = len(rows)
    gates: list[CanaryGateResult] = []
    warnings: list[CanaryGateResult] = []

    preflight = run_preflight(for_canary=True)
    gates.append(
        _gate(
            "preflight_canary",
            preflight.canary_allowed,
            preflight.canary_allowed,
            True,
            sample_count,
            "Critical dependencies available for canary",
        )
    )

    hold_ok, hold_reason = stage_hold_satisfied()
    gates.append(
        _gate(
            "stage_hold_period",
            hold_ok,
            hold_reason,
            "satisfied",
            sample_count,
            "Minimum observation window for current stage",
        )
    )

    latency_deltas = [
        float(r["latency_delta_ms"])
        for r in rows
        if r.get("latency_delta_ms") is not None
    ]
    p95_delta = _percentile(latency_deltas, 95)
    max_p95 = float(getattr(settings, "canary_max_p95_latency_delta_ms", 5000.0))
    gates.append(
        _gate(
            "latency_p95_delta",
            p95_delta is None or p95_delta <= max_p95,
            p95_delta,
            max_p95,
            sample_count,
            "Canonical p95 latency delta within configured bound",
        )
    )

    fallback_count = sum(1 for r in rows if r.get("fallback_reason"))
    fallback_rate = (fallback_count / sample_count) if sample_count else 0.0
    max_fallback = float(getattr(settings, "canary_max_fallback_rate", 0.10))
    gates.append(
        _gate(
            "fallback_rate",
            sample_count == 0 or fallback_rate <= max_fallback,
            round(fallback_rate, 4),
            max_fallback,
            sample_count,
            "Canary fallback rate acceptable",
        )
    )

    wins = {}
    for r in rows:
        status = r.get("comparison_status") or "inconclusive"
        wins[status] = wins.get(status, 0) + 1
    if sample_count == 0:
        gates.append(
            _gate(
                "quality_comparison",
                False,
                0,
                ">0 samples",
                0,
                "No canary paired samples yet",
            )
        )
    else:
        canonical_wins = int(wins.get("canonical_better", 0))
        legacy_wins = int(wins.get("legacy_better", 0))
        gates.append(
            _gate(
                "quality_comparison",
                canonical_wins >= legacy_wins,
                f"canonical={canonical_wins},legacy={legacy_wins}",
                "canonical>=legacy",
                sample_count,
                "Aggregate quality not worse than legacy",
            )
        )

    blocking = [g for g in gates if not g.passed]
    if not blocking and sample_count >= int(getattr(settings, "canary_minimum_samples", 30)):
        if target_stage == "100":
            recommendation = GateRecommendation.READY_FOR_FULL_CUTOVER
        else:
            recommendation = GateRecommendation.READY_FOR_CANARY
    elif not blocking:
        recommendation = GateRecommendation.READY_FOR_CANARY
        warnings.append(
            _gate(
                "sample_size_warning",
                False,
                sample_count,
                settings.canary_minimum_samples,
                sample_count,
                "Samples below recommended minimum for full confidence",
            )
        )
    else:
        recommendation = GateRecommendation.NOT_READY

    return CanaryGateEvaluation(
        eligible=not blocking,
        blocking_gates=blocking,
        warnings=warnings,
        passed_gates=[g for g in gates if g.passed],
        recommendation=recommendation,
        sample_count=sample_count,
    )


def evaluate_rollback_conditions() -> CanaryGateEvaluation:
    """Hard rollback conditions — operator should set CANARY_ENABLED=false."""
    rows = _paired_rows("canary")
    sample_count = len(rows)
    gates: list[CanaryGateResult] = []
    rollback_triggers: list[CanaryGateResult] = []

    security = sum(
        1 for r in rows if "tenant" in str(r.get("errors", [])).lower()
    )
    if security > 0:
        rollback_triggers.append(
            _gate(
                "tenant_isolation_violation",
                False,
                security,
                0,
                sample_count,
                "Tenant isolation violation detected",
            )
        )

    fallback_count = sum(1 for r in rows if r.get("fallback_reason"))
    if sample_count >= 10:
        fallback_rate = fallback_count / sample_count
        max_fb = float(getattr(settings, "canary_rollback_fallback_rate", 0.25))
        if fallback_rate > max_fb:
            rollback_triggers.append(
                _gate(
                    "abnormal_fallback_rate",
                    False,
                    round(fallback_rate, 4),
                    max_fb,
                    sample_count,
                    "Fallback rate exceeds rollback threshold",
                )
            )

    latency_deltas = [
        float(r["latency_delta_ms"])
        for r in rows
        if r.get("latency_delta_ms") is not None
    ]
    p95 = _percentile(latency_deltas, 95)
    rollback_p95 = float(getattr(settings, "canary_rollback_p95_latency_delta_ms", 10000.0))
    if p95 is not None and p95 > rollback_p95:
        rollback_triggers.append(
            _gate(
                "severe_latency_regression",
                False,
                p95,
                rollback_p95,
                sample_count,
                "p95 latency delta exceeds rollback threshold",
            )
        )

    return CanaryGateEvaluation(
        eligible=not rollback_triggers,
        blocking_gates=rollback_triggers,
        recommendation=(
            GateRecommendation.NOT_READY
            if rollback_triggers
            else GateRecommendation.READY_FOR_CANARY
        ),
        sample_count=sample_count,
    )


def evaluate_full_cutover_readiness() -> CanaryGateEvaluation:
    """Full cutover eligibility requires sustained multi-window evidence."""
    shadow_gate = evaluate_shadow_evidence_gate()
    canary_gate = evaluate_canary_promotion_gates(target_stage="100")
    rollback = evaluate_rollback_conditions()

    all_gates = (
        list(shadow_gate.passed_gates)
        + list(shadow_gate.blocking_gates)
        + list(canary_gate.passed_gates)
        + list(canary_gate.blocking_gates)
        + list(rollback.blocking_gates)
    )
    blocking = (
        shadow_gate.blocking_gates
        + canary_gate.blocking_gates
        + rollback.blocking_gates
    )

    windows_ok = _evaluate_stability_windows()
    if not windows_ok:
        blocking.append(
            _gate(
                "sustained_stability",
                False,
                "unstable",
                "stable",
                canary_gate.sample_count,
                "Performance not stable across evaluation windows",
            )
        )

    if blocking:
        recommendation = GateRecommendation.NOT_READY
    elif canary_gate.recommendation == GateRecommendation.READY_FOR_FULL_CUTOVER:
        recommendation = GateRecommendation.READY_FOR_FULL_CUTOVER
    else:
        recommendation = GateRecommendation.READY_FOR_CANARY

    return CanaryGateEvaluation(
        eligible=not blocking,
        blocking_gates=blocking,
        warnings=canary_gate.warnings,
        passed_gates=[g for g in all_gates if g.passed],
        recommendation=recommendation,
        sample_count=max(shadow_gate.sample_count, canary_gate.sample_count),
    )


def _evaluate_stability_windows() -> bool:
    """Require at least two windows with non-regressing canonical win rate."""
    rows = sorted(
        _paired_rows("canary"),
        key=lambda r: float(r.get("created_at") or 0.0),
    )
    if len(rows) < 20:
        return False
    mid = len(rows) // 2
    windows = (rows[:mid], rows[mid:])

    def win_rate(window: list[dict[str, Any]]) -> float:
        if not window:
            return 0.0
        wins = sum(1 for r in window if r.get("comparison_status") == "canonical_better")
        return wins / len(window)

    rates = [win_rate(w) for w in windows]
    return all(r >= 0.4 for r in rates) and abs(rates[0] - rates[1]) <= 0.3
