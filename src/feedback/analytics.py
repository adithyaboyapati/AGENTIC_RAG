"""User feedback analytics with tenant-safe aggregation (Phase 8)."""

from __future__ import annotations

from typing import Any

from src.feedback.store import list_feedback, summarize_feedback


def build_feedback_analytics(*, window_hours: float = 168.0) -> dict[str, Any]:
    """Aggregate feedback metrics without cross-tenant leakage in public summaries."""
    import time

    cutoff = time.time() - window_hours * 3600
    rows = list_feedback(limit=2000)
    recent = [r for r in rows if _epoch(r.get("created_at")) >= cutoff]

    up = sum(1 for r in recent if r.get("rating") == "up")
    down = sum(1 for r in recent if r.get("rating") == "down")
    total = up + down

    by_strategy: dict[str, dict[str, int]] = {}
    by_route: dict[str, dict[str, int]] = {}
    categories: dict[str, int] = {}

    for r in recent:
        if r.get("rating") != "down":
            continue
        mode = str(r.get("mode") or "unknown")
        route = str(r.get("route") or "unknown")
        by_strategy.setdefault(mode, {"down": 0, "up": 0})
        by_strategy[mode]["down"] += 1
        by_route.setdefault(route, {"down": 0})
        by_route[route]["down"] += 1
        for c in r.get("categories") or []:
            categories[str(c)] = categories.get(str(c), 0) + 1

    summary = summarize_feedback(limit=min(2000, len(recent) or 1))

    return {
        "window_hours": window_hours,
        "total_ratings": total,
        "positive_rate": round(up / total, 4) if total else None,
        "negative_rate": round(down / total, 4) if total else None,
        "feedback_rate_proxy": len(recent),
        "top_failure_categories": summary.get("top_categories") or [],
        "by_mode": summary.get("by_mode") or [],
        "negative_by_strategy": by_strategy,
        "negative_by_route": by_route,
        "category_counts": categories,
        "tenant_scoped": False,
        "note": "Aggregates are global operator view; per-tenant drill-down requires authenticated tenant filter.",
    }


def _epoch(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        import time as _time

        return _time.mktime(_time.strptime(str(value)[:19], "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return 0.0
