"""Per-request cost attribution (Phase 8)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.evaluation.production_observer import list_observations


@dataclass
class CostAttributionSummary:
    window_hours: float
    total_cost_usd: float
    total_requests: int
    cost_per_request: float
    by_strategy: dict[str, float] = field(default_factory=dict)
    by_model: dict[str, float] = field(default_factory=dict)
    by_tenant: dict[str, float] = field(default_factory=dict)
    by_route: dict[str, float] = field(default_factory=dict)


def build_cost_attribution(*, window_hours: float = 24.0) -> CostAttributionSummary:
    rows = list_observations(since_hours=window_hours)
    total_cost = sum(float(r.get("cost_usd") or 0) for r in rows)
    n = len(rows)

    by_strategy: dict[str, float] = {}
    by_model: dict[str, float] = {}
    by_tenant: dict[str, float] = {}
    by_route: dict[str, float] = {}

    for row in rows:
        cost = float(row.get("cost_usd") or 0)
        strategy = str(row.get("strategy") or "unknown")
        model = str(row.get("model_id") or "unknown")
        tenant = str(row.get("tenant_id") or "default")
        route = str(row.get("route") or "unknown")
        by_strategy[strategy] = by_strategy.get(strategy, 0.0) + cost
        by_model[model] = by_model.get(model, 0.0) + cost
        by_tenant[tenant] = by_tenant.get(tenant, 0.0) + cost
        by_route[route] = by_route.get(route, 0.0) + cost

    return CostAttributionSummary(
        window_hours=window_hours,
        total_cost_usd=round(total_cost, 6),
        total_requests=n,
        cost_per_request=round(total_cost / n, 6) if n else 0.0,
        by_strategy={k: round(v, 6) for k, v in sorted(by_strategy.items())},
        by_model={k: round(v, 6) for k, v in sorted(by_model.items())},
        by_tenant={k: round(v, 6) for k, v in sorted(by_tenant.items())},
        by_route={k: round(v, 6) for k, v in sorted(by_route.items())},
    )


def observation_cost_record(
    *,
    request_id: str,
    tenant_id: str,
    route: str,
    strategy: str,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    llm_calls: int,
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "tenant_id": tenant_id,
        "route": route,
        "strategy": strategy,
        "model_id": model_id,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "llm_calls": llm_calls,
    }
