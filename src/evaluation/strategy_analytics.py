"""Strategy effectiveness analytics (Phase 8)."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from src.evaluation.production_observer import list_observations


@dataclass
class StrategyStats:
    strategy: str
    count: int
    avg_latency_ms: float
    avg_cost_usd: float
    avg_evidence_count: float
    error_rate: float
    verification_pass_rate: float
    negative_proxy_rate: float


@dataclass
class StrategyAnalyticsReport:
    window_hours: float
    total_requests: int
    strategies: list[StrategyStats] = field(default_factory=list)
    auto_vs_simple_delta: dict[str, float] = field(default_factory=dict)


def build_strategy_analytics(*, window_hours: float = 24.0) -> StrategyAnalyticsReport:
    rows = list_observations(since_hours=window_hours)
    by_strategy: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        strategy = str(row.get("strategy") or "unknown")
        by_strategy.setdefault(strategy, []).append(row)

    stats: list[StrategyStats] = []
    for strategy, group in sorted(by_strategy.items()):
        n = len(group)
        latencies = [float(r.get("latency_ms") or 0) for r in group]
        costs = [float(r.get("cost_usd") or 0) for r in group]
        evidence = [float(r.get("evidence_count") or 0) for r in group]
        errors = sum(1 for r in group if r.get("error_code"))
        verified = sum(
            1 for r in group if str(r.get("verification_status") or "").lower() in {"pass", "ok", "verified"}
        )
        stats.append(
            StrategyStats(
                strategy=strategy,
                count=n,
                avg_latency_ms=round(statistics.mean(latencies) if latencies else 0.0, 2),
                avg_cost_usd=round(statistics.mean(costs) if costs else 0.0, 6),
                avg_evidence_count=round(statistics.mean(evidence) if evidence else 0.0, 2),
                error_rate=round(errors / n, 4) if n else 0.0,
                verification_pass_rate=round(verified / n, 4) if n else 0.0,
                negative_proxy_rate=round(
                    sum(1 for r in group if int(r.get("zero_evidence") or 0)) / n, 4
                )
                if n
                else 0.0,
            )
        )

    simple = next((s for s in stats if s.strategy == "simple"), None)
    auto = next((s for s in stats if s.strategy == "auto"), None)
    delta: dict[str, float] = {}
    if simple and auto and simple.count > 0 and auto.count > 0:
        delta = {
            "latency_ms": round(auto.avg_latency_ms - simple.avg_latency_ms, 2),
            "cost_usd": round(auto.avg_cost_usd - simple.avg_cost_usd, 6),
            "evidence_count": round(auto.avg_evidence_count - simple.avg_evidence_count, 2),
            "error_rate": round(auto.error_rate - simple.error_rate, 4),
        }

    return StrategyAnalyticsReport(
        window_hours=window_hours,
        total_requests=len(rows),
        strategies=stats,
        auto_vs_simple_delta=delta,
    )
