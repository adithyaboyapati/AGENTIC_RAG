"""CI and production evaluation regression gates (Phase 8)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GateSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    INFORMATIONAL = "informational"


@dataclass
class EvalGate:
    name: str
    severity: GateSeverity
    passed: bool
    message: str
    value: float | None = None
    threshold: float | None = None


@dataclass
class EvalGateReport:
    gates: list[EvalGate] = field(default_factory=list)
    overall_status: str = "pass"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "gates": [
                {
                    "name": g.name,
                    "severity": g.severity.value,
                    "passed": g.passed,
                    "message": g.message,
                    "value": g.value,
                    "threshold": g.threshold,
                }
                for g in self.gates
            ],
            "warnings": self.warnings,
        }


def run_eval_gates(*, offline_summary: dict[str, Any] | None = None) -> EvalGateReport:
    """Evaluate protected metrics with critical/high/medium/informational classification."""
    report = EvalGateReport()
    offline = offline_summary or {}

    # Critical: golden set must load
    item_count = int(offline.get("item_count") or 0)
    errors = offline.get("errors") or []
    report.gates.append(
        EvalGate(
            name="golden_set_loads",
            severity=GateSeverity.CRITICAL,
            passed=item_count > 0 and not errors,
            message=f"golden items={item_count}, errors={len(errors)}",
            value=float(item_count),
        )
    )

    # High: offline keyword coverage proxy (from retrieval_metrics validate)
    keyword_coverage = float(offline.get("keyword_coverage") or 0.0)
    report.gates.append(
        EvalGate(
            name="golden_keyword_coverage",
            severity=GateSeverity.HIGH,
            passed=keyword_coverage >= 0.95,
            message=f"keyword_coverage={keyword_coverage:.3f}",
            value=keyword_coverage,
            threshold=0.95,
        )
    )

    # Informational: regression queue size
    try:
        from src.evaluation.dataset_store import list_cases

        candidates = len(list_cases(status="candidate"))
        report.gates.append(
            EvalGate(
                name="regression_candidate_queue",
                severity=GateSeverity.INFORMATIONAL,
                passed=True,
                message=f"candidates={candidates}",
                value=float(candidates),
            )
        )
    except Exception as exc:
        report.warnings.append(f"candidate_queue_unavailable:{exc}")

    critical_fail = any(not g.passed for g in report.gates if g.severity == GateSeverity.CRITICAL)
    high_fail = any(not g.passed for g in report.gates if g.severity == GateSeverity.HIGH)
    if critical_fail:
        report.overall_status = "fail_critical"
    elif high_fail:
        report.overall_status = "fail_high"
    else:
        report.overall_status = "pass"

    return report


def main() -> None:
    """CLI entry for CI eval gate."""
    from src.evaluation.retrieval_metrics import validate_golden_set_offline

    offline = validate_golden_set_offline()
    report = run_eval_gates(offline_summary=offline)
    print(report.to_dict())
    if report.overall_status.startswith("fail"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
