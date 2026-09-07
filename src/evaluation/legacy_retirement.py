"""Legacy architecture retirement inventory and readiness gates (Phase 7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.config import settings
from src.evaluation.canary_gates import evaluate_full_cutover_readiness, evaluate_rollback_conditions
from src.evaluation.canary_rollout import get_rollout_state
from src.evaluation.preflight import run_preflight
from src.evaluation.shadow_storage import list_shadow_results


class LegacyRetirementStatus(str, Enum):
    NOT_READY = "NOT_READY"
    READY_FOR_DEPRECATION = "READY_FOR_DEPRECATION"
    READY_FOR_REMOVAL = "READY_FOR_REMOVAL"


CANONICAL_PIPELINE_VERSION = "v1"


@dataclass(frozen=True)
class LegacyComponentRecord:
    component: str
    referenced_by: str
    runtime_critical: bool
    removable: bool
    evidence: str


@dataclass
class LegacyRetirementEvaluation:
    status: LegacyRetirementStatus
    blocking_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    legacy_fallback_rate: float | None = None
    legacy_invocation_count: int = 0
    canary_sample_count: int = 0
    inventory_count: int = 0


def legacy_dependency_inventory() -> tuple[LegacyComponentRecord, ...]:
    """Static inventory of legacy components and their dependency class."""
    return (
        LegacyComponentRecord(
            component="src/graph/router_graph.py",
            referenced_by="runner (removed Phase 7), tests",
            runtime_critical=False,
            removable=True,
            evidence="Superseded by canonical_graph classify/retrieve",
        ),
        LegacyComponentRecord(
            component="src/graph/crag_graph.py",
            referenced_by="runner (removed), tests",
            runtime_critical=False,
            removable=True,
            evidence="Superseded by canonical evidence_management + rewrite",
        ),
        LegacyComponentRecord(
            component="src/graph/decompose_graph.py",
            referenced_by="agent_graph subgraph, runner (removed)",
            runtime_critical=False,
            removable=True,
            evidence="Superseded by canonical decompose strategy",
        ),
        LegacyComponentRecord(
            component="src/graph/multi_hop_graph.py",
            referenced_by="agent_graph subgraph, runner (removed)",
            runtime_critical=False,
            removable=True,
            evidence="Superseded by canonical multi_hop strategy",
        ),
        LegacyComponentRecord(
            component="src/graph/tools_graph.py",
            referenced_by="agent_graph subgraph, runner (removed)",
            runtime_critical=False,
            removable=True,
            evidence="Superseded by canonical federation retrieval",
        ),
        LegacyComponentRecord(
            component="src/graph/agent_graph.py",
            referenced_by="runner (removed), default API mode",
            runtime_critical=False,
            removable=True,
            evidence="Superseded by canonical_graph + strategy_heuristics",
        ),
        LegacyComponentRecord(
            component="src/graph/consensus_graph.py",
            referenced_by="runner (removed), API mode consensus",
            runtime_critical=False,
            removable=True,
            evidence="No canonical equivalent; deprecated API mode maps to auto",
        ),
        LegacyComponentRecord(
            component="src/rag/baseline.py",
            referenced_by="runner (removed)",
            runtime_critical=False,
            removable=True,
            evidence="Superseded by canonical simple retrieve path",
        ),
        LegacyComponentRecord(
            component="runner._dispatch legacy branches",
            referenced_by="run_agent, stream_agent, comparative_eval",
            runtime_critical=False,
            removable=True,
            evidence="Replaced by canonical-primary dispatch",
        ),
        LegacyComponentRecord(
            component="to_legacy_adapter",
            referenced_by="shadow_runner canary path (removed Phase 7)",
            runtime_critical=False,
            removable=True,
            evidence="Replaced by contracts.api_response.canonical_to_api_response",
        ),
        LegacyComponentRecord(
            component="shadow run_legacy_pipeline",
            referenced_by="traffic_policy fallback (Phase 7 safe failure)",
            runtime_critical=False,
            removable=True,
            evidence="Historical shadow rows retained; live legacy execution removed",
        ),
        LegacyComponentRecord(
            component="API legacy mode enum values",
            referenced_by="server.py, frontend",
            runtime_critical=False,
            removable=False,
            evidence="Deprecated mapping retained for client compatibility",
        ),
        LegacyComponentRecord(
            component="src/graph/shared_nodes.py",
            referenced_by="canonical_graph",
            runtime_critical=True,
            removable=False,
            evidence="Canonical uses invoke_router, run_direct_answer, run_web_search_answer",
        ),
        LegacyComponentRecord(
            component="src/chains/generation.py",
            referenced_by="canonical_graph, shared_nodes",
            runtime_critical=True,
            removable=False,
            evidence="Canonical generation uses rag_chain and shared web/direct chains",
        ),
        LegacyComponentRecord(
            component="shadow_eval.db historical rows",
            referenced_by="canary_gates, legacy_retirement metrics",
            runtime_critical=False,
            removable=False,
            evidence="Historical paired evaluation data — must be preserved",
        ),
    )


def _legacy_fallback_stats() -> tuple[int, int, float]:
    rows = [r for r in list_shadow_results(limit=5000) if r.get("execution_mode") == "canary"]
    if not rows:
        return 0, 0, 0.0
    fallbacks = sum(1 for r in rows if r.get("fallback_reason"))
    rate = fallbacks / len(rows)
    return len(rows), fallbacks, rate


def evaluate_legacy_retirement_readiness() -> LegacyRetirementEvaluation:
    """Determine whether legacy runtime code may be deprecated or removed."""
    blocking: list[str] = []
    warnings: list[str] = []
    rollout = get_rollout_state()
    preflight = run_preflight(for_canary=True)
    cutover = evaluate_full_cutover_readiness()
    rollback = evaluate_rollback_conditions()
    sample_count, fallback_count, fallback_rate = _legacy_fallback_stats()
    max_fallback = float(getattr(settings, "legacy_retirement_max_fallback_rate", 0.05))

    if not settings.canonical_primary:
        blocking.append("canonical_primary=false")

    if not preflight.canary_allowed:
        blocking.append("preflight_canary_blocked")

    if rollback.blocking_gates:
        blocking.extend(g.reason for g in rollback.blocking_gates)

    if sample_count > 0 and fallback_rate > max_fallback:
        blocking.append(
            f"legacy_fallback_rate={fallback_rate:.4f}>{max_fallback} over {sample_count} canary samples"
        )

    if cutover.recommendation.value == "NOT_READY" and sample_count < int(
        getattr(settings, "legacy_retirement_min_canary_samples", 30)
    ):
        warnings.append(
            f"insufficient_canary_evidence:{sample_count}<"
            f"{getattr(settings, 'legacy_retirement_min_canary_samples', 30)}"
        )

    operator_approved = bool(getattr(settings, "legacy_removal_operator_approved", False))

    if blocking:
        status = LegacyRetirementStatus.NOT_READY
    elif operator_approved and cutover.eligible and (
        sample_count == 0 or fallback_rate <= max_fallback
    ):
        status = LegacyRetirementStatus.READY_FOR_REMOVAL
    elif settings.canonical_primary:
        status = LegacyRetirementStatus.READY_FOR_DEPRECATION
        if not operator_approved:
            warnings.append("operator_approval_pending_for_runtime_removal")
        if not cutover.eligible:
            warnings.append(f"cutover_not_eligible:{cutover.recommendation.value}")
    else:
        status = LegacyRetirementStatus.NOT_READY

    return LegacyRetirementEvaluation(
        status=status,
        blocking_reasons=blocking,
        warnings=warnings,
        legacy_fallback_rate=fallback_rate if sample_count else None,
        legacy_invocation_count=fallback_count,
        canary_sample_count=sample_count,
        inventory_count=len(legacy_dependency_inventory()),
    )


def inventory_table() -> list[dict[str, Any]]:
    return [
        {
            "component": row.component,
            "referenced_by": row.referenced_by,
            "runtime_critical": row.runtime_critical,
            "removable": row.removable,
            "evidence": row.evidence,
        }
        for row in legacy_dependency_inventory()
    ]
