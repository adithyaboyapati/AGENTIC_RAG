"""Cutover decision engine based on measured shadow evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.evaluation.shadow_reports import build_shadow_report


class CutoverRecommendation(str, Enum):
    NOT_READY = "NOT READY"
    READY_FOR_LIMITED_CANARY = "READY FOR LIMITED CANARY"
    READY_FOR_FULL_CUTOVER = "READY FOR FULL CUTOVER"


@dataclass
class CutoverGate:
    name: str
    passed: bool
    evidence: str


@dataclass
class CutoverDecision:
    recommendation: CutoverRecommendation
    gates: list[CutoverGate]
    blockers: list[str]
    sample_count: int


def evaluate_cutover_gates(
    report: dict[str, Any] | None = None,
    *,
    min_sample_count: int = 30,
) -> CutoverDecision:
    report = report or build_shadow_report()
    sample_count = int(report.get("sample_count") or 0)
    gates: list[CutoverGate] = []
    blockers: list[str] = []

    gates.append(
        CutoverGate(
            name="minimum_sample",
            passed=sample_count >= min_sample_count,
            evidence=f"sample_count={sample_count}, required>={min_sample_count}",
        )
    )
    if sample_count < min_sample_count:
        blockers.append(f"Insufficient paired samples ({sample_count} < {min_sample_count})")

    overall = report.get("overall") or {}
    deltas = overall.get("deltas") or {}
    wins = overall.get("comparison_wins") or {}

    faith_delta = deltas.get("faithfulness")
    faith_gate = faith_delta is not None and faith_delta >= -0.05
    gates.append(
        CutoverGate(
            name="faithfulness_non_regression",
            passed=faith_gate,
            evidence=f"faithfulness_delta={faith_delta}",
        )
    )
    if not faith_gate:
        blockers.append("Canonical faithfulness regression exceeds tolerance or unmeasured")

    latency_delta = deltas.get("latency_p95")
    latency_gate = latency_delta is None or latency_delta <= 5000
    gates.append(
        CutoverGate(
            name="latency_p95_within_target",
            passed=latency_gate,
            evidence=f"latency_delta_p95_ms={latency_delta}",
        )
    )
    if not latency_gate:
        blockers.append("Canonical p95 latency delta exceeds 5000ms tolerance")

    canonical_wins = int(wins.get("canonical_better") or 0)
    legacy_wins = int(wins.get("legacy_better") or 0)
    inconclusive = int(wins.get("inconclusive") or 0)
    quality_gate = sample_count > 0 and canonical_wins >= legacy_wins
    gates.append(
        CutoverGate(
            name="quality_not_worse_than_legacy",
            passed=quality_gate,
            evidence=(
                f"canonical_wins={canonical_wins}, legacy_wins={legacy_wins}, "
                f"inconclusive={inconclusive}"
            ),
        )
    )
    if not quality_gate:
        blockers.append("Canonical does not win or tie quality comparisons often enough")

    error_rate = int(wins.get("error") or 0)
    reliability_gate = sample_count == 0 or (error_rate / sample_count) <= 0.05
    gates.append(
        CutoverGate(
            name="reliability_error_rate",
            passed=reliability_gate,
            evidence=f"errors={error_rate}, sample_count={sample_count}",
        )
    )
    if not reliability_gate:
        blockers.append("Canonical paired error rate above 5%")

    all_pass = all(g.passed for g in gates)
    strong_pass = all_pass and canonical_wins > legacy_wins and faith_delta is not None and faith_delta >= 0

    if strong_pass and sample_count >= min_sample_count * 3:
        recommendation = CutoverRecommendation.READY_FOR_FULL_CUTOVER
    elif all_pass:
        recommendation = CutoverRecommendation.READY_FOR_LIMITED_CANARY
    else:
        recommendation = CutoverRecommendation.NOT_READY

    return CutoverDecision(
        recommendation=recommendation,
        gates=gates,
        blockers=blockers,
        sample_count=sample_count,
    )
