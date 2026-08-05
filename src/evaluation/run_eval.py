"""Phase 8: Evaluation harness for RAG quality metrics."""

from __future__ import annotations

import json
from dataclasses import dataclass

from src.runner import run_agent


@dataclass
class EvalResult:
    """Result from one query evaluation."""

    question: str
    mode: str
    answer: str
    latency_ms: float
    sources_count: int
    steps_count: int


def eval_baseline() -> None:
    """Run evaluation on example questions across all modes."""
    questions = [
        "What is retrieval-augmented generation?",
        "Compare naive RAG and advanced RAG",
        "What fallback does CRAG use when retrieval fails?",
        "What is 100 * 50?",
    ]

    modes = ["baseline", "router", "crag", "decompose", "multi_hop", "tools", "agentic"]

    results = []

    print("=" * 80)
    print("AGENTIC RAG EVALUATION SUITE")
    print("=" * 80)

    for question in questions:
        print(f"\n\nQuestion: {question}")
        print("-" * 80)

        for mode in modes:
            try:
                import time

                start = time.time()
                result = run_agent(question, mode)
                elapsed = (time.time() - start) * 1000

                eval_result = EvalResult(
                    question=question,
                    mode=mode,
                    answer=result.answer[:100],
                    latency_ms=elapsed,
                    sources_count=len(result.sources),
                    steps_count=len(result.steps),
                )
                results.append(eval_result)

                print(
                    f"{mode:12} | latency={elapsed:6.0f}ms | sources={eval_result.sources_count} | steps={eval_result.steps_count}"
                )
            except Exception as e:
                print(f"{mode:12} | ERROR: {e}")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    if results:
        by_mode = {}
        for r in results:
            if r.mode not in by_mode:
                by_mode[r.mode] = []
            by_mode[r.mode].append(r)

        print("\nLatency by mode (avg):")
        for mode in modes:
            if mode in by_mode:
                avg_latency = sum(r.latency_ms for r in by_mode[mode]) / len(by_mode[mode])
                print(f"  {mode:12} {avg_latency:6.0f}ms")

    with open("eval_results.json", "w") as f:
        json.dump(
            [
                {
                    "question": r.question,
                    "mode": r.mode,
                    "latency_ms": r.latency_ms,
                    "sources_count": r.sources_count,
                    "steps_count": r.steps_count,
                }
                for r in results
            ],
            f,
            indent=2,
        )
    print("\nResults saved to eval_results.json")


if __name__ == "__main__":
    eval_baseline()
