"""Continuous evaluation orchestrator — scheduled and failure-driven (Phase 8)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.evaluation.dataset_store import append_eval_run, list_cases
from src.evaluation.eval_gates import EvalGateReport, run_eval_gates
from src.evaluation.retrieval_metrics import load_golden_set, validate_golden_set_offline
from src.evaluation.versioning import current_eval_manifest

logger = logging.getLogger(__name__)


@dataclass
class ContinuousEvalResult:
    trigger: str
    manifest: dict[str, str]
    gate_report: EvalGateReport
    regression_candidates: int = 0
    golden_cases: int = 0
    run_id: str = ""
    warnings: list[str] = field(default_factory=list)


def run_scheduled_evaluation(*, dataset_version: str = "golden-v1") -> ContinuousEvalResult:
    """Run offline validation + eval gates on schedule."""
    manifest = current_eval_manifest(dataset_version=dataset_version).to_dict()
    golden = validate_golden_set_offline()
    gate_report = run_eval_gates(offline_summary=golden)

    summary = {
        "trigger": "scheduled",
        "golden_validation": golden,
        "gates": gate_report.to_dict(),
        "regression_case_count": len(list_cases(status="regression")),
        "candidate_case_count": len(list_cases(status="candidate")),
    }
    run_id = append_eval_run(
        trigger="scheduled",
        manifest=manifest,
        summary=summary,
        gate_status=gate_report.overall_status,
    )
    return ContinuousEvalResult(
        trigger="scheduled",
        manifest=manifest,
        gate_report=gate_report,
        regression_candidates=len(list_cases(status="candidate")),
        golden_cases=len(load_golden_set()),
        run_id=run_id,
        warnings=gate_report.warnings,
    )


def run_failure_driven_evaluation(*, failure_category: str | None = None) -> ContinuousEvalResult:
    """Re-evaluate when production failures or feedback create new candidates."""
    manifest = current_eval_manifest(dataset_version="regression-queue").to_dict()
    candidates = list_cases(status="candidate")
    if failure_category:
        candidates = [c for c in candidates if c.get("failure_category") == failure_category]

    golden = validate_golden_set_offline()
    gate_report = run_eval_gates(offline_summary=golden)

    summary = {
        "trigger": "failure_driven",
        "failure_category": failure_category,
        "candidate_count": len(candidates),
        "gates": gate_report.to_dict(),
    }
    run_id = append_eval_run(
        trigger="failure_driven",
        manifest=manifest,
        summary=summary,
        gate_status=gate_report.overall_status,
    )
    return ContinuousEvalResult(
        trigger="failure_driven",
        manifest=manifest,
        gate_report=gate_report,
        regression_candidates=len(candidates),
        run_id=run_id,
        warnings=gate_report.warnings,
    )
