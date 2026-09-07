"""Shadow evaluation reports and segmentation."""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from src.evaluation.shadow_storage import list_shadow_results


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, int(round(0.95 * (len(ordered) - 1))))
    return round(ordered[idx], 4)


def _segment_key(row: dict[str, Any], dimension: str) -> str:
    canonical = row.get("canonical_metrics") or {}
    legacy = row.get("legacy_metrics") or {}
    if dimension == "route":
        return str(canonical.get("route") or legacy.get("route") or "unknown")
    if dimension == "strategy":
        return str(canonical.get("strategy") or "unknown")
    if dimension == "legacy_mode":
        return str(row.get("legacy_mode") or "unknown")
    if dimension == "comparison_status":
        return str(row.get("comparison_status") or "unknown")
    if dimension == "question_length":
        qlen = int((legacy.get("answer_length") or 0))
        return "short" if qlen < 120 else "long"
    return "unknown"


def build_shadow_report(*, limit: int = 1000, tenant_id: str | None = None) -> dict[str, Any]:
    rows = list_shadow_results(limit=limit, tenant_id=tenant_id)
    if not rows:
        return {"sample_count": 0, "message": "no shadow results stored"}

    legacy_faith = []
    canonical_faith = []
    legacy_latency = []
    canonical_latency = []
    legacy_cost = []
    canonical_cost = []
    wins = defaultdict(int)
    disagreements = defaultdict(int)

    for row in rows:
        legacy = row["legacy_metrics"]
        canonical = row["canonical_metrics"]
        if legacy.get("faithfulness") is not None:
            legacy_faith.append(float(legacy["faithfulness"]))
        if canonical.get("faithfulness") is not None:
            canonical_faith.append(float(canonical["faithfulness"]))
        if legacy.get("latency_ms") is not None:
            legacy_latency.append(float(legacy["latency_ms"]))
        if canonical.get("latency_ms") is not None:
            canonical_latency.append(float(canonical["latency_ms"]))
        if legacy.get("cost_usd") is not None:
            legacy_cost.append(float(legacy["cost_usd"]))
        if canonical.get("cost_usd") is not None:
            canonical_cost.append(float(canonical["cost_usd"]))
        wins[row.get("comparison_status") or "unknown"] += 1
        disagreements[row.get("disagreement_class") or "unknown"] += 1

    latency_deltas = [
        float(row["latency_delta_ms"])
        for row in rows
        if row.get("latency_delta_ms") is not None
    ]

    segments: dict[str, dict[str, Any]] = {}
    for dimension in ("route", "strategy", "legacy_mode", "comparison_status", "question_length"):
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[_segment_key(row, dimension)].append(row)
        segments[dimension] = {
            key: {
                "sample_count": len(items),
                "canonical_wins": sum(
                    1 for item in items if item.get("comparison_status") == "canonical_better"
                ),
                "legacy_wins": sum(
                    1 for item in items if item.get("comparison_status") == "legacy_better"
                ),
                "inconclusive": sum(
                    1 for item in items if item.get("comparison_status") == "inconclusive"
                ),
            }
            for key, items in grouped.items()
        }

    return {
        "sample_count": len(rows),
        "overall": {
            "comparison_wins": dict(wins),
            "disagreement_classes": dict(disagreements),
            "legacy": _aggregate_pipeline(legacy_faith, legacy_latency, legacy_cost),
            "canonical": _aggregate_pipeline(canonical_faith, canonical_latency, canonical_cost),
            "deltas": {
                "faithfulness": _delta_mean(canonical_faith, legacy_faith),
                "latency_ms": _mean(latency_deltas),
                "latency_p95": _p95(latency_deltas),
                "cost_usd": _delta_mean(canonical_cost, legacy_cost),
            },
        },
        "segments": segments,
    }


def _aggregate_pipeline(
    faith: list[float],
    latency: list[float],
    cost: list[float],
) -> dict[str, float | None]:
    return {
        "faithfulness_mean": _mean(faith),
        "faithfulness_samples": len(faith),
        "latency_p50": statistics.median(latency) if latency else None,
        "latency_p95": _p95(latency),
        "cost_mean": _mean(cost),
    }


def _delta_mean(a: list[float], b: list[float]) -> float | None:
    if not a or not b or len(a) != len(b):
        if a and b:
            return round(_mean(a) - _mean(b), 4)  # type: ignore[operator]
        return None
    return round(sum(x - y for x, y in zip(a, b, strict=True)) / len(a), 4)


def format_shadow_report(report: dict[str, Any]) -> str:
    if report.get("sample_count", 0) == 0:
        return "No shadow evaluation results available."
    overall = report["overall"]
    lines = [
        "# Shadow Evaluation Report",
        "",
        f"Sample count: {report['sample_count']}",
        "",
        "## Overall",
        f"- Comparison wins: {overall['comparison_wins']}",
        f"- Disagreements: {overall['disagreement_classes']}",
        "",
        "## Quality",
        f"- Legacy faithfulness mean: {overall['legacy'].get('faithfulness_mean', 'N/A')}",
        f"- Canonical faithfulness mean: {overall['canonical'].get('faithfulness_mean', 'N/A')}",
        f"- Delta: {overall['deltas'].get('faithfulness', 'N/A')}",
        "",
        "## Operations",
        f"- Legacy latency p95: {overall['legacy'].get('latency_p95', 'N/A')}",
        f"- Canonical latency p95: {overall['canonical'].get('latency_p95', 'N/A')}",
        f"- Latency delta mean: {overall['deltas'].get('latency_ms', 'N/A')}",
        f"- Cost delta mean: {overall['deltas'].get('cost_usd', 'N/A')}",
    ]
    return "\n".join(lines)
