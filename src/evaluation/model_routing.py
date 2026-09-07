"""Policy-based model routing abstraction (Phase 8).

Does not add new providers — selects among configured models by task type.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.config import settings


class ModelTask(str, Enum):
    GENERATION = "generation"
    VERIFICATION = "verification"
    STRATEGY = "strategy"
    ROUTING = "routing"
    SIMPLE = "simple"


@dataclass(frozen=True)
class ModelRouteDecision:
    task: str
    model_id: str
    provider: str
    reason: str


def route_model(task: ModelTask | str, *, complexity: str = "normal") -> ModelRouteDecision:
    """Select a model for a task based on configurable policy."""
    task_name = task.value if isinstance(task, ModelTask) else str(task)
    primary = settings.openai_model
    fallback = settings.groq_model if settings.llm_fallback_enabled else None

    if task_name == ModelTask.VERIFICATION.value:
        return ModelRouteDecision(
            task=task_name,
            model_id=primary,
            provider="openai",
            reason="verification uses primary judge model",
        )

    if task_name in {ModelTask.ROUTING.value, ModelTask.STRATEGY.value} and complexity == "simple":
        return ModelRouteDecision(
            task=task_name,
            model_id=primary,
            provider="openai",
            reason="lightweight routing/strategy on primary model",
        )

    if task_name == ModelTask.SIMPLE.value and complexity == "simple":
        cheap = getattr(settings, "simple_model_id", "") or primary
        return ModelRouteDecision(
            task=task_name,
            model_id=cheap,
            provider="openai",
            reason="simple questions may use configured simple_model_id",
        )

    if complexity == "complex":
        return ModelRouteDecision(
            task=task_name,
            model_id=primary,
            provider="openai",
            reason="complex multi-hop/decompose uses primary model",
        )

    return ModelRouteDecision(
        task=task_name,
        model_id=primary,
        provider="openai",
        reason="default primary model",
    )


def model_quality_cost_summary(observations: list[dict]) -> list[dict]:
    """Aggregate quality/cost proxies per model from observations."""
    by_model: dict[str, list[dict]] = {}
    for row in observations:
        model = str(row.get("model_id") or "unknown")
        by_model.setdefault(model, []).append(row)

    rows: list[dict] = []
    for model, group in sorted(by_model.items()):
        n = len(group)
        total_cost = sum(float(r.get("cost_usd") or 0) for r in group)
        total_latency = sum(float(r.get("latency_ms") or 0) for r in group)
        verified = sum(
            1 for r in group if str(r.get("verification_status") or "").lower() in {"pass", "ok", "verified"}
        )
        errors = sum(1 for r in group if r.get("error_code"))
        quality_proxy = verified / n if n else 0.0
        cost_per_req = total_cost / n if n else 0.0
        latency_per_req = total_latency / n if n else 0.0
        rows.append(
            {
                "model_id": model,
                "sample_count": n,
                "verification_pass_rate_proxy": round(quality_proxy, 4),
                "error_rate": round(errors / n, 4) if n else 0.0,
                "avg_latency_ms": round(latency_per_req, 2),
                "avg_cost_usd": round(cost_per_req, 6),
                "quality_per_dollar": round(quality_proxy / cost_per_req, 2) if cost_per_req > 0 else None,
                "quality_per_second": round(quality_proxy / (latency_per_req / 1000), 2)
                if latency_per_req > 0
                else None,
                "metrics_are_proxy": True,
            }
        )
    return rows
