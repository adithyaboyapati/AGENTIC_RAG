"""Basic performance benchmark for canonical strategies."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any

from src.config import PROJECT_ROOT


@dataclass
class BenchmarkResult:
    strategy: str
    question: str
    execution_time_ms: float
    llm_calls: int | None = None
    retrieval_calls: int | None = None
    reranker_calls: int | None = None
    verification_calls: int = 1
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    latency_ms: float | None = None
    raw: dict[str, Any] | None = None


REPRESENTATIVE_QUESTIONS = (
    "What is Retrieval-Augmented Generation?",
    "Compare naive RAG and modular RAG.",
    "How does multi-hop retrieval help complex questions?",
)


def benchmark_strategy(question: str, strategy: str | None) -> BenchmarkResult:
    from src.graph.canonical_graph import ask_canonical

    started = time.monotonic()
    response = ask_canonical(question, force_strategy=strategy)
    elapsed = round((time.monotonic() - started) * 1000, 2)
    verification_calls = 1 if response.verification is not None else 0
    return BenchmarkResult(
        strategy=strategy or "auto",
        question=question,
        execution_time_ms=elapsed,
        llm_calls=None,
        retrieval_calls=None,
        reranker_calls=None,
        verification_calls=verification_calls,
        latency_ms=response.latency_ms or elapsed,
        raw={
            "route": response.route,
            "strategy": response.strategy,
            "response_status": response.response_status,
        },
    )


def run_benchmark(
    questions: tuple[str, ...] = REPRESENTATIVE_QUESTIONS,
    strategies: tuple[str | None, ...] = ("simple", "decompose", "multi_hop", None),
) -> list[BenchmarkResult]:
    results: list[BenchmarkResult] = []
    for strategy in strategies:
        for question in questions:
            results.append(benchmark_strategy(question, strategy))
    return results


def write_benchmark_report(results: list[BenchmarkResult]) -> None:
    out_dir = PROJECT_ROOT / "eval_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = [asdict(item) for item in results]
    (out_dir / "canonical_benchmark.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
