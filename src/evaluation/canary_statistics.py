"""Paired statistical analysis for shadow/canary evaluation."""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from src.evaluation.shadow_storage import list_shadow_results


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


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return round(statistics.median(values), 4)


def _wilson_ci(wins: int, total: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if total <= 0:
        return None, None
    p = wins / total
    denom = 1 + z**2 / total
    center = (p + z**2 / (2 * total)) / denom
    margin = (z * ((p * (1 - p) / total) + z**2 / (4 * total**2)) ** 0.5) / denom
    return round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4)


def analyze_paired_results(
    *,
    execution_mode: str | None = None,
    limit: int = 5000,
) -> dict[str, Any]:
    rows = list_shadow_results(limit=limit)
    if execution_mode:
        rows = [r for r in rows if r.get("execution_mode") == execution_mode]

    sample_count = len(rows)
    if sample_count == 0:
        return {"sample_count": 0, "message": "no paired observations"}

    comparison_counts: dict[str, int] = defaultdict(int)
    latency_deltas: list[float] = []
    cost_deltas: list[float] = []
    token_deltas: list[float] = []
    faith_deltas: list[float] = []

    for row in rows:
        comparison_counts[row.get("comparison_status") or "inconclusive"] += 1
        if row.get("latency_delta_ms") is not None:
            latency_deltas.append(float(row["latency_delta_ms"]))
        if row.get("cost_delta_usd") is not None:
            cost_deltas.append(float(row["cost_delta_usd"]))
        if row.get("token_delta") is not None:
            token_deltas.append(float(row["token_delta"]))
        qd = row.get("quality_deltas") or {}
        if qd.get("faithfulness") is not None:
            faith_deltas.append(float(qd["faithfulness"]))

    canonical_wins = comparison_counts.get("canonical_better", 0)
    ci_low, ci_high = _wilson_ci(canonical_wins, sample_count)

    segments: dict[str, dict[str, Any]] = {}
    for dimension in ("route", "strategy", "legacy_mode"):
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            if dimension == "legacy_mode":
                key = str(row.get("legacy_mode") or "unknown")
            else:
                key = str((row.get("canonical_metrics") or {}).get(dimension) or "unknown")
            grouped[key].append(row)
        segments[dimension] = {
            key: _segment_summary(items)
            for key, items in grouped.items()
        }

    return {
        "sample_count": sample_count,
        "comparison": dict(comparison_counts),
        "canonical_win_rate": round(canonical_wins / sample_count, 4),
        "canonical_win_rate_ci95": {"low": ci_low, "high": ci_high},
        "latency_delta_ms": {
            "mean": _mean(latency_deltas),
            "median": _median(latency_deltas),
            "p50": _percentile(latency_deltas, 50),
            "p95": _percentile(latency_deltas, 95),
        },
        "cost_delta_usd": {
            "mean": _mean(cost_deltas),
            "median": _median(cost_deltas),
        },
        "token_delta": {
            "mean": _mean(token_deltas),
            "median": _median(token_deltas),
        },
        "faithfulness_delta": {
            "mean": _mean(faith_deltas),
            "median": _median(faith_deltas),
        },
        "segments": segments,
    }


def _segment_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(1 for r in rows if r.get("comparison_status") == "canonical_better")
    return {
        "sample_count": len(rows),
        "canonical_wins": wins,
        "legacy_wins": sum(1 for r in rows if r.get("comparison_status") == "legacy_better"),
        "equivalent": sum(1 for r in rows if r.get("comparison_status") == "equivalent"),
        "inconclusive": sum(1 for r in rows if r.get("comparison_status") == "inconclusive"),
        "canonical_win_rate": round(wins / len(rows), 4) if rows else None,
    }
