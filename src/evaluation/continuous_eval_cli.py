"""CLI entry for continuous evaluation."""

from __future__ import annotations

import argparse
import json

from src.evaluation.continuous_eval import (
    run_failure_driven_evaluation,
    run_scheduled_evaluation,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run continuous evaluation")
    parser.add_argument(
        "--trigger",
        choices=["scheduled", "failure_driven"],
        default="scheduled",
    )
    args = parser.parse_args()

    result = (
        run_scheduled_evaluation()
        if args.trigger == "scheduled"
        else run_failure_driven_evaluation()
    )
    payload = {
        "trigger": result.trigger,
        "run_id": result.run_id,
        "manifest": result.manifest,
        "gate_status": result.gate_report.overall_status,
        "warnings": result.warnings,
    }
    print(json.dumps(payload, indent=2))
    if result.gate_report.overall_status.startswith("fail"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
