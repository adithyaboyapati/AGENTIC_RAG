"""Turn thumbs-down feedback into an eval regression set.

Usage:
    python -m src.feedback.export --out data/eval/feedback_regressions.json
    python -m src.feedback.export --since-days 7 --min-count 1

Each negative rating becomes a golden-set candidate with the question, the
answer the user rejected, their comment, and the sources that were cited. A
human still promotes items into ``data/eval/golden_qa.json`` — this file is
the triage queue, not the gate.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from src.config import PROJECT_ROOT
from src.feedback.store import list_feedback

DEFAULT_OUT = PROJECT_ROOT / "data" / "eval" / "feedback_regressions.json"


def _created_epoch(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return time.mktime(time.strptime(str(value)[:19], "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return 0.0


def build_regression_items(since_days: int | None = None, limit: int = 1000) -> list[dict]:
    rows = list_feedback(limit=limit, rating="down")
    cutoff = time.time() - since_days * 86400 if since_days else None
    items: list[dict] = []
    for r in rows:
        if cutoff is not None and _created_epoch(r.get("created_at")) < cutoff:
            continue
        items.append(
            {
                "question": r.get("question"),
                "mode": r.get("mode"),
                "rejected_answer": r.get("answer"),
                "user_comment": r.get("comment") or "",
                "categories": r.get("categories") or [],
                "cited_sources": r.get("sources") or [],
                "feedback_id": r.get("id"),
                "created_at": r.get("created_at"),
                # Fill these in when promoting to golden_qa.json
                "expected_keywords": [],
                "expected_chunk_ids": [],
                "notes": "Promoted from user feedback — verify expected answer before use.",
            }
        )
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description="Export negative feedback as eval candidates")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--since-days", type=int, default=None)
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()

    items = build_regression_items(since_days=args.since_days, limit=args.limit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(items)} negative-feedback item(s) to {args.out}")


if __name__ == "__main__":
    main()
