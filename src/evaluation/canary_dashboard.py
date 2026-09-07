"""Operator-facing canary rollout dashboard report."""

from __future__ import annotations

from typing import Any

from src.evaluation.canary_gates import (
    evaluate_canary_promotion_gates,
    evaluate_full_cutover_readiness,
    evaluate_rollback_conditions,
    evaluate_shadow_evidence_gate,
)
from src.evaluation.canary_rollout import get_rollout_state
from src.evaluation.canary_statistics import analyze_paired_results
from src.evaluation.preflight import run_preflight


def build_canary_dashboard() -> dict[str, Any]:
    rollout = get_rollout_state()
    preflight = run_preflight(for_canary=rollout.canary_enabled)
    shadow_stats = analyze_paired_results(execution_mode="shadow")
    canary_stats = analyze_paired_results(execution_mode="canary")
    shadow_gate = evaluate_shadow_evidence_gate()
    promotion_gate = evaluate_canary_promotion_gates()
    rollback_gate = evaluate_rollback_conditions()
    cutover = evaluate_full_cutover_readiness()

    return {
        "traffic": {
            "legacy_percent": rollout.legacy_traffic_percent,
            "canonical_percent": rollout.canonical_traffic_percent,
            "shadow_percent": rollout.shadow_traffic_percent,
            "canary_stage": rollout.canary_stage,
            "kill_switch_active": rollout.kill_switch_active,
            "canonical_primary": rollout.canonical_primary,
        },
        "reliability": {
            "canary_sample_count": canary_stats.get("sample_count", 0),
            "shadow_sample_count": shadow_stats.get("sample_count", 0),
            "fallback_rate_required": "see canary_gates",
            "rollback_triggers": [g.gate_name for g in rollback_gate.blocking_gates],
        },
        "quality": {
            "shadow": shadow_stats.get("comparison", {}),
            "canary": canary_stats.get("comparison", {}),
            "faithfulness_delta_mean": canary_stats.get("faithfulness_delta", {}).get("mean"),
        },
        "performance": canary_stats.get("latency_delta_ms", {}),
        "economics": {
            "cost_delta_mean": canary_stats.get("cost_delta_usd", {}).get("mean"),
            "token_delta_mean": canary_stats.get("token_delta", {}).get("mean"),
        },
        "segments": canary_stats.get("segments", {}),
        "gates": {
            "shadow_evidence_eligible": shadow_gate.eligible,
            "promotion_eligible": promotion_gate.eligible,
            "rollback_clear": rollback_gate.eligible,
            "cutover_recommendation": cutover.recommendation.value,
        },
        "preflight": preflight.to_dict(),
    }


def format_canary_dashboard(report: dict[str, Any]) -> str:
    traffic = report.get("traffic", {})
    lines = [
        "# Canary Rollout Dashboard",
        "",
        "## Traffic",
        f"- Legacy: {traffic.get('legacy_percent', 'N/A')}%",
        f"- Canonical: {traffic.get('canonical_percent', 'N/A')}%",
        f"- Shadow sampling: {traffic.get('shadow_percent', 'N/A')}%",
        f"- Stage: {traffic.get('canary_stage', 'N/A')}",
        f"- Kill switch: {traffic.get('kill_switch_active', 'N/A')}",
        "",
        "## Gates",
        f"- Shadow evidence eligible: {report.get('gates', {}).get('shadow_evidence_eligible')}",
        f"- Promotion eligible: {report.get('gates', {}).get('promotion_eligible')}",
        f"- Cutover recommendation: {report.get('gates', {}).get('cutover_recommendation')}",
        "",
        "## Quality (canary paired)",
        f"- Samples: {report.get('reliability', {}).get('canary_sample_count', 0)}",
        f"- Comparison: {report.get('quality', {}).get('canary', {})}",
    ]
    return "\n".join(lines)
