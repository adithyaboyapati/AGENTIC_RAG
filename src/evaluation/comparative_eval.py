"""Comparative evaluation harness: canonical pipeline variants."""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT
from src.evaluation.retrieval_metrics import load_golden_set, score_keyword_hits
from src.runner import _dispatch

DEFAULT_GOLDEN_PATH = PROJECT_ROOT / "data" / "eval" / "golden_qa.json"


@dataclass
class ComparativeMetrics:
    pipeline: str
    recall_at_k: float | None = None
    precision_at_k: float | None = None
    mrr: float | None = None
    ndcg: float | None = None
    faithfulness: float | None = None
    answer_relevance: float | None = None
    correctness: float | None = None
    citation_correctness: float | None = None
    citation_completeness: float | None = None
    abstention_correct: bool | None = None
    retrieval_quality: float | None = None
    routing_accuracy: float | None = None
    strategy_accuracy: float | None = None
    llm_calls: int | None = None
    retry_count: int | None = None
    latency_ms: float | None = None
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    strategy_source: str | None = None
    route: str | None = None
    strategy: str | None = None
    decision_source: str | None = None
    verification_status: str | None = None
    response_status: str | None = None
    sample_size: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


PIPELINES = (
    "canonical-simple",
    "canonical-decompose",
    "canonical-multi-hop",
    "canonical-auto",
)


def _fmt(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _ndcg_at_k(relevances: list[float]) -> float:
    if not relevances:
        return 0.0
    dcg = sum(rel / __import__("math").log2(i + 2) for i, rel in enumerate(relevances))
    ideal = sorted(relevances, reverse=True)
    idcg = sum(rel / __import__("math").log2(i + 2) for i, rel in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def score_retrieval_from_results(
    results: list[Any],
    *,
    expected_chunk_ids: list[str] | None,
    expected_keywords: list[str] | None,
    k: int = 6,
) -> tuple[float, float, float, float]:
    """Compute recall@k, precision@k, MRR, NDCG from RetrievalResult objects."""
    chunk_ids = [getattr(r, "chunk_id", "") for r in results[:k]]
    contents = [getattr(r, "content", "") for r in results[:k]]
    expected_ids = [str(x) for x in (expected_chunk_ids or []) if x]
    if expected_ids:
        expected_set = set(expected_ids)
        hits = [1.0 if cid in expected_set else 0.0 for cid in chunk_ids]
        recall = sum(1 for cid in chunk_ids if cid in expected_set) / len(expected_ids)
        precision = sum(hits) / max(1, len(chunk_ids))
        mrr = 0.0
        for rank, cid in enumerate(chunk_ids, start=1):
            if cid in expected_set:
                mrr = 1.0 / rank
                break
        ndcg = _ndcg_at_k(hits)
        return recall, precision, mrr, ndcg

    hit, recall, mrr, _ = score_keyword_hits(contents, expected_keywords)
    precision = recall if hit else 0.0
    ndcg = _ndcg_at_k([1.0 if hit else 0.0])
    return recall, precision, mrr, ndcg


def run_pipeline(question: str, pipeline: str, *, tenant: str = "default") -> ComparativeMetrics:
    """Run one pipeline and capture comparable metrics."""
    from src.schemas import RBACContext

    rbac = RBACContext(tenant_id=tenant)
    started = time.monotonic()

    if pipeline.startswith("canonical"):
        from src.graph.canonical_graph import ask_canonical

        force = None
        if pipeline != "canonical" and pipeline != "canonical-auto":
            force = pipeline.removeprefix("canonical-").replace("-", "_")
        response = ask_canonical(question, rbac_context=rbac, force_strategy=force)
        latency_ms = response.latency_ms or round((time.monotonic() - started) * 1000, 2)
        verification = response.verification
        return ComparativeMetrics(
            pipeline=pipeline,
            faithfulness=verification.faithfulness if verification else None,
            answer_relevance=verification.answer_relevance if verification else None,
            citation_correctness=verification.citation_correctness if verification else None,
            citation_completeness=verification.citation_completeness if verification else None,
            latency_ms=latency_ms,
            route=response.route,
            strategy=response.strategy,
            verification_status=verification.outcome if verification else None,
            response_status=response.response_status,
            llm_calls=None,
            sample_size=1,
            raw={"mode": response.mode, "strategy": response.strategy},
        )

    legacy = _dispatch(question, pipeline, rbac_context=rbac)
    latency_ms = round((time.monotonic() - started) * 1000, 2)
    return ComparativeMetrics(
        pipeline=pipeline,
        latency_ms=latency_ms,
        route=legacy.route,
        sample_size=1,
        raw={
            "mode": legacy.mode,
            "answer_len": len(legacy.answer or ""),
            "sources": len(legacy.sources or []),
        },
    )


def run_comparative_eval(
    question: str,
    pipelines: tuple[str, ...] = PIPELINES,
    *,
    tenant: str = "default",
) -> list[ComparativeMetrics]:
    return [run_pipeline(question, pipeline, tenant=tenant) for pipeline in pipelines]


def run_golden_comparative_eval(
    *,
    path: Path | None = None,
    pipelines: tuple[str, ...] = PIPELINES,
    limit: int | None = None,
    live: bool = False,
) -> dict[str, Any]:
    """Evaluate golden set across pipelines. Set live=True to invoke real graphs."""
    items = load_golden_set(path)
    if limit is not None:
        items = items[:limit]

    per_pipeline: dict[str, list[ComparativeMetrics]] = {p: [] for p in pipelines}
    unavailable: list[str] = []

    for item in items:
        question = item["question"]
        if live:
            for pipeline in pipelines:
                try:
                    per_pipeline[pipeline].append(run_pipeline(question, pipeline))
                except Exception as exc:
                    unavailable.append(f"{pipeline}:{type(exc).__name__}")
        else:
            # Offline retrieval-only scoring for canonical retrieval path.
            from src.retrieval.canonical_adapter import retrieve_candidates
            from src.schemas import RBACContext

            results = retrieve_candidates(
                question,
                query_id="eval",
                rbac_context=RBACContext(),
            )
            recall, precision, mrr, ndcg = score_retrieval_from_results(
                results,
                expected_chunk_ids=item.get("expected_chunk_ids"),
                expected_keywords=item.get("expected_keywords"),
            )
            metric = ComparativeMetrics(
                pipeline="canonical-retrieval-offline",
                recall_at_k=recall,
                precision_at_k=precision,
                mrr=mrr,
                ndcg=ndcg,
                sample_size=1,
                raw={"question": question, "labeled": bool(item.get("expected_chunk_ids"))},
            )
            per_pipeline.setdefault("canonical-retrieval-offline", []).append(metric)

    summary: dict[str, Any] = {
        "pipelines": {},
        "unavailable_errors": unavailable,
        "golden_count": len(items),
        "live": live,
    }
    for pipeline, rows in per_pipeline.items():
        if not rows:
            continue
        latencies = [r.latency_ms for r in rows if r.latency_ms is not None]
        summary["pipelines"][pipeline] = {
            "sample_size": len(rows),
            "recall_at_k": _mean([r.recall_at_k for r in rows]),
            "precision_at_k": _mean([r.precision_at_k for r in rows]),
            "mrr": _mean([r.mrr for r in rows]),
            "ndcg": _mean([r.ndcg for r in rows]),
            "faithfulness": _mean([r.faithfulness for r in rows]),
            "answer_relevance": _mean([r.answer_relevance for r in rows]),
            "citation_correctness": _mean([r.citation_correctness for r in rows]),
            "correctness": _mean([r.correctness for r in rows]),
            "latency_p50_ms": statistics.median(latencies) if latencies else None,
            "latency_p95_ms": _p95(latencies),
            "llm_calls": _mean([float(r.llm_calls) for r in rows if r.llm_calls is not None]),
            "cost_usd": _mean([r.cost_usd for r in rows]),
        }
    return summary


def _mean(values: list[float | None]) -> float | None:
    nums = [float(v) for v in values if v is not None]
    return round(sum(nums) / len(nums), 4) if nums else None


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, int(round(0.95 * (len(ordered) - 1))))
    return round(ordered[idx], 2)


def format_decision_table(results: dict[str, Any]) -> str:
    header = (
        "| Pipeline | Recall | Faithfulness | Correctness | Citation | "
        "LLM Calls | Cost | p95 | Verdict |"
    )
    sep = "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"
    rows = [header, sep]
    pipelines = results.get("pipelines", {})
    for pipeline, metrics in sorted(pipelines.items()):
        verdict = "insufficient_data"
        if metrics.get("faithfulness") is not None and metrics.get("recall_at_k") is not None:
            verdict = "review"
        rows.append(
            "| "
            + " | ".join(
                [
                    pipeline,
                    _fmt(metrics.get("recall_at_k")),
                    _fmt(metrics.get("faithfulness")),
                    _fmt(metrics.get("correctness")),
                    _fmt(metrics.get("citation_correctness")),
                    _fmt(metrics.get("llm_calls")),
                    _fmt(metrics.get("cost_usd")),
                    _fmt(metrics.get("latency_p95_ms")),
                    verdict,
                ]
            )
            + " |"
        )
    return "\n".join(rows)


def format_comparison_table(results: list[ComparativeMetrics]) -> str:
    header = "| Pipeline | Faithfulness | Retrieval | Citation | LLM Calls | Latency | Cost |"
    sep = "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"
    rows = []
    for item in results:
        rows.append(
            f"| {item.pipeline} | {_fmt(item.faithfulness)} | {_fmt(item.retrieval_quality)} | {_fmt(item.citation_correctness)} | {_fmt(item.llm_calls)} | {_fmt(item.latency_ms)} | {_fmt(item.cost_usd)} |"
        )
    return "\n".join([header, sep, *rows])


def write_eval_report(report: dict[str, Any], filename: str = "comparative_eval.json") -> Path:
    out_dir = PROJECT_ROOT / "eval_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out_path
