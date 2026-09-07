"""Detect unnecessary agentic work (Phase 8)."""

from __future__ import annotations

from dataclasses import dataclass

from src.evaluation.production_observer import list_observations


@dataclass(frozen=True)
class AgenticEfficiencyReport:
    window_hours: float
    sample_count: int
    unnecessary_strategy_llm_rate: float
    ineffective_retry_rate: float
    unnecessary_multihop_rate: float


def build_agentic_efficiency_report(*, window_hours: float = 24.0) -> AgenticEfficiencyReport:
    rows = list_observations(since_hours=window_hours)
    n = len(rows)
    if n == 0:
        return AgenticEfficiencyReport(window_hours, 0, 0.0, 0.0, 0.0)

    strategy_llm_redundant = sum(1 for r in rows if r.get("strategy_llm_redundant"))
    ineffective_retry = sum(1 for r in rows if r.get("ineffective_retry"))
    unnecessary_multihop = sum(1 for r in rows if r.get("unnecessary_multihop"))

    return AgenticEfficiencyReport(
        window_hours=window_hours,
        sample_count=n,
        unnecessary_strategy_llm_rate=round(strategy_llm_redundant / n, 4),
        ineffective_retry_rate=round(ineffective_retry / n, 4),
        unnecessary_multihop_rate=round(unnecessary_multihop / n, 4),
    )
