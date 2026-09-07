"""Replay recorded requests through the shadow runner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from src.config import PROJECT_ROOT
from src.evaluation.shadow_models import ExecutionMode
from src.evaluation.shadow_reports import build_shadow_report, format_shadow_report
from src.evaluation.shadow_runner import eval_config_hash, run_paired_evaluation
from src.schemas import RBACContext

DEFAULT_REPLAY_PATH = PROJECT_ROOT / "data" / "eval" / "recorded_requests.jsonl"


def iter_recorded_requests(path: Path | None = None) -> Iterator[dict[str, Any]]:
    replay_path = path or DEFAULT_REPLAY_PATH
    if not replay_path.exists():
        return iter(())
    with open(replay_path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def run_replay(
    *,
    path: Path | None = None,
    limit: int | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    results: list[str] = []
    errors: list[str] = []
    for idx, item in enumerate(iter_recorded_requests(path)):
        if limit is not None and idx >= limit:
            break
        try:
            rbac = RBACContext(
                tenant_id=str(item.get("tenant_id") or "default"),
                user_roles=list(item.get("user_roles") or ["public"]),
                classification=str(item.get("classification") or "public"),
            )
            run_paired_evaluation(
                question=str(item["question"]),
                legacy_mode=str(item.get("legacy_mode") or item.get("mode") or "agentic"),
                rbac_context=rbac,
                request_id=str(item.get("request_id") or f"replay-{idx}"),
                execution_mode=ExecutionMode.REPLAY,
                canonical_strategy=item.get("canonical_strategy"),
                use_memory=bool(item.get("use_memory", False)),
                persist=persist,
            )
            results.append(str(item.get("request_id") or idx))
        except Exception as exc:
            errors.append(f"{idx}:{type(exc).__name__}")
    report = build_shadow_report(limit=max(len(results) + len(errors), 1))
    return {
        "eval_config_hash": eval_config_hash(),
        "processed": len(results),
        "errors": errors,
        "report": report,
        "report_text": format_shadow_report(report),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Replay recorded requests through shadow runner")
    parser.add_argument("--path", type=str, default=str(DEFAULT_REPLAY_PATH))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    result = run_replay(path=Path(args.path), limit=args.limit)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
