"""Offline retrieval metrics: recall@k, MRR, hit-rate against a golden set."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.config import PROJECT_ROOT

DEFAULT_GOLDEN_PATH = PROJECT_ROOT / "data" / "eval" / "golden_qa.json"


@dataclass
class RetrievalScore:
    question: str
    hit: bool
    recall_at_k: float
    mrr: float
    retrieved_chunk_ids: list[str]
    expected_chunk_ids: list[str]
    expected_keywords_hit: list[str]


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


def score_keyword_hits(
    contents: list[str],
    expected_keywords: list[str] | None,
) -> tuple[bool, float, float, list[str]]:
    """Pure keyword scoring against already-retrieved passage texts (no I/O).

    Returns (hit, recall, mrr, keywords_hit). Used by CI offline gates and
    by ``score_retrieval`` when chunk IDs are not available.
    """
    normalized = [_normalize(c) for c in contents]
    keywords = [k for k in (expected_keywords or []) if k]
    if not keywords:
        hit = bool(contents)
        return hit, (1.0 if hit else 0.0), (1.0 if hit else 0.0), []

    keyword_hits = [kw for kw in keywords if any(_normalize(kw) in c for c in normalized)]
    hit = bool(keyword_hits)
    recall = len(keyword_hits) / len(keywords)
    mrr = 0.0
    if keyword_hits:
        for rank, content in enumerate(normalized, start=1):
            if any(_normalize(kw) in content for kw in keyword_hits):
                mrr = 1.0 / rank
                break
    return hit, recall, mrr, keyword_hits


def load_golden_set(path: Path | None = None) -> list[dict]:
    golden_path = path or DEFAULT_GOLDEN_PATH
    with open(golden_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Golden set must be a JSON list")
    return data


def validate_golden_set_offline(path: Path | None = None) -> dict:
    """CI-safe checks: file loads, required fields present, keyword lists non-empty.

    Does not call embeddings or Chroma.
    """
    items = load_golden_set(path)
    errors: list[str] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"item[{i}] is not an object")
            continue
        if not (item.get("question") or "").strip():
            errors.append(f"item[{i}] missing question")
        keywords = item.get("expected_keywords") or []
        chunk_ids = item.get("expected_chunk_ids") or []
        if not keywords and not chunk_ids:
            errors.append(f"item[{i}] needs expected_keywords or expected_chunk_ids")

    # Smoke the pure scorer so CI exercises scoring logic without a vector store
    demo_hit, demo_recall, _, _ = score_keyword_hits(
        ["retrieval augmented generation uses a vector store"],
        ["retrieval", "vector store"],
    )
    if not demo_hit or demo_recall < 1.0:
        errors.append("internal keyword scorer smoke failed")

    return {
        "ok": not errors,
        "count": len(items),
        "errors": errors,
    }


def score_retrieval(
    question: str,
    expected_chunk_ids: list[str] | None = None,
    expected_keywords: list[str] | None = None,
    top_k: int | None = None,
) -> RetrievalScore:
    """Score one query against expected chunk IDs and/or keywords in content."""
    from src.retrieval.retriever import retrieve

    docs = retrieve(question, top_k=top_k)
    retrieved_ids = [
        str(doc.metadata.get("chunk_id") or doc.metadata.get("id") or "")
        for doc in docs
    ]
    retrieved_ids = [rid for rid in retrieved_ids if rid]

    expected_ids = [str(x) for x in (expected_chunk_ids or []) if x]
    keywords = [k for k in (expected_keywords or []) if k]

    id_hits = 0
    mrr = 0.0
    if expected_ids:
        expected_set = set(expected_ids)
        id_hits = sum(1 for rid in retrieved_ids if rid in expected_set)
        for rank, rid in enumerate(retrieved_ids, start=1):
            if rid in expected_set:
                mrr = 1.0 / rank
                break
        recall = id_hits / len(expected_ids)
        hit = id_hits > 0
        keyword_hits: list[str] = []
    else:
        hit, recall, mrr, keyword_hits = score_keyword_hits(
            [doc.page_content for doc in docs],
            keywords,
        )

    return RetrievalScore(
        question=question,
        hit=hit,
        recall_at_k=recall,
        mrr=mrr,
        retrieved_chunk_ids=retrieved_ids,
        expected_chunk_ids=expected_ids,
        expected_keywords_hit=keyword_hits,
    )


def evaluate_golden_retrieval(
    path: Path | None = None,
    top_k: int | None = None,
) -> dict:
    """Run recall@k / MRR over the golden Q&A file."""
    items = load_golden_set(path)
    scores = [
        score_retrieval(
            question=item["question"],
            expected_chunk_ids=item.get("expected_chunk_ids"),
            expected_keywords=item.get("expected_keywords"),
            top_k=top_k,
        )
        for item in items
    ]
    n = len(scores) or 1
    return {
        "count": len(scores),
        "hit_rate": sum(1 for s in scores if s.hit) / n,
        "recall_at_k": sum(s.recall_at_k for s in scores) / n,
        "mrr": sum(s.mrr for s in scores) / n,
        "details": [
            {
                "question": s.question,
                "hit": s.hit,
                "recall_at_k": s.recall_at_k,
                "mrr": s.mrr,
                "retrieved_chunk_ids": s.retrieved_chunk_ids,
                "expected_chunk_ids": s.expected_chunk_ids,
                "expected_keywords_hit": s.expected_keywords_hit,
            }
            for s in scores
        ],
    }


def check_thresholds(
    report: dict,
    *,
    min_recall: float,
    min_mrr: float,
    min_hit_rate: float,
) -> list[str]:
    """Return human-readable failures for a scored report (empty = passing)."""
    failures: list[str] = []
    if report["recall_at_k"] < min_recall:
        failures.append(
            f"recall@k {report['recall_at_k']:.3f} < {min_recall:.3f}"
        )
    if report["mrr"] < min_mrr:
        failures.append(f"MRR {report['mrr']:.3f} < {min_mrr:.3f}")
    if report["hit_rate"] < min_hit_rate:
        failures.append(
            f"hit_rate {report['hit_rate']:.3f} < {min_hit_rate:.3f}"
        )
    return failures


def _write_report(report: dict) -> Path:
    out_dir = PROJECT_ROOT / "eval_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "retrieval_metrics.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Golden-set retrieval metrics")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Validate golden_qa.json without calling Chroma/OpenAI (CI)",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Score against the live index and exit non-zero on regression",
    )
    parser.add_argument("--min-recall", type=float, default=None)
    parser.add_argument("--min-mrr", type=float, default=None)
    parser.add_argument("--min-hit-rate", type=float, default=None)
    args = parser.parse_args()

    if args.offline:
        report = validate_golden_set_offline()
        print(json.dumps(report, indent=2))
        raise SystemExit(0 if report["ok"] else 1)

    report = evaluate_golden_retrieval()
    print(json.dumps(report, indent=2))

    if not args.gate:
        return

    # CLI flag > environment > default, so the nightly workflow can tune
    # thresholds without a code change.
    def _threshold(flag: float | None, env: str, default: float) -> float:
        if flag is not None:
            return flag
        return float(os.getenv(env, default))

    failures = check_thresholds(
        report,
        min_recall=_threshold(args.min_recall, "MIN_RECALL", 0.70),
        min_mrr=_threshold(args.min_mrr, "MIN_MRR", 0.50),
        min_hit_rate=_threshold(args.min_hit_rate, "MIN_HIT_RATE", 0.80),
    )
    out_path = _write_report(report)
    print(f"\nReport written to {out_path}")

    if failures:
        print("\nRetrieval quality regressed:")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)
    print("\nRetrieval quality within thresholds.")


if __name__ == "__main__":
    main()
