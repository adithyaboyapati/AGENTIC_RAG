"""
Comprehensive evaluation of all 7 modes using RAGAS-inspired metrics.

Run:
    python -m src.evaluation.evaluate_all_modes

Metrics:
  - Faithfulness: Is answer grounded in context?
  - Answer Relevance: Does answer address question?
  - Context Precision: Are retrieved docs relevant?
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

from src.evaluation.metrics import evaluate_metrics
from src.runner import run_agent


@dataclass
class ModeEvalResult:
    """Evaluation result for one mode on one question."""

    mode: str
    question: str
    latency_ms: float
    faithfulness: float
    answer_relevance: float
    context_precision: float
    overall_score: float


def evaluate_query(question: str, mode: str) -> ModeEvalResult | None:
    """Run query and evaluate with RAGAS metrics."""
    try:
        print(f"  {mode:12}", end=" ... ", flush=True)
        start = time.time()
        result = run_agent(question, mode)
        elapsed = (time.time() - start) * 1000

        # Judge against retrieved chunk text (not source path labels)
        if result.context_docs:
            context = "\n---\n".join(result.context_docs)
        elif result.citations:
            context = "\n---\n".join(
                c.snippet for c in result.citations if c.snippet
            ) or "(No retrieval)"
        else:
            context = "(No retrieval)"

        metrics = evaluate_metrics(question, result.answer, context)

        eval_result = ModeEvalResult(
            mode=mode,
            question=question,
            latency_ms=elapsed,
            faithfulness=metrics.faithfulness,
            answer_relevance=metrics.answer_relevance,
            context_precision=metrics.context_precision,
            overall_score=metrics.overall_score,
        )
        print(f"✓ ({elapsed:.0f}ms)")
        return eval_result
    except Exception as e:
        print(f"✗ ({str(e)[:50]})")
        return None


def main() -> None:
    """Run comprehensive evaluation across all modes."""
    questions = [
        "What is retrieval-augmented generation?",
        "How does Self-RAG differ from traditional RAG?",
        "Compare naive RAG and advanced RAG",
    ]

    modes = ["baseline", "router", "crag", "decompose", "multi_hop", "tools", "agentic"]

    results: list[ModeEvalResult] = []

    print("=" * 90)
    print("RAGAS EVALUATION — AGENTIC RAG SYSTEM")
    print("=" * 90)

    for i, question in enumerate(questions, 1):
        print(f"\n📊 Question {i}: {question[:60]}...")
        print("-" * 90)

        for mode in modes:
            result = evaluate_query(question, mode)
            if result:
                results.append(result)

    # Summary table
    print("\n" + "=" * 90)
    print("RESULTS BY MODE")
    print("=" * 90)
    print(f"\n{'Mode':<12} | {'Queries':<7} | {'Avg Latency':<12} | {'Faithfulness':<13} | {'Relevance':<10} | {'Overall':<8}")
    print("-" * 90)

    by_mode = {}
    for r in results:
        if r.mode not in by_mode:
            by_mode[r.mode] = []
        by_mode[r.mode].append(r)

    for mode in modes:
        if mode in by_mode:
            evals = by_mode[mode]
            avg_latency = sum(e.latency_ms for e in evals) / len(evals)
            avg_faith = sum(e.faithfulness for e in evals) / len(evals)
            avg_relev = sum(e.answer_relevance for e in evals) / len(evals)
            avg_overall = sum(e.overall_score for e in evals) / len(evals)

            print(
                f"{mode:<12} | {len(evals):<7} | {avg_latency:>10.0f}ms | "
                f"{avg_faith:>11.3f}  | {avg_relev:>9.3f} | {avg_overall:>7.3f}"
            )

    # Save results
    results_data = [asdict(r) for r in results]
    with open("ragas_eval_results.json", "w") as f:
        json.dump(results_data, f, indent=2)

    print("\n✅ Results saved to ragas_eval_results.json")

    # Recommendations
    print("\n" + "=" * 90)
    print("INSIGHTS")
    print("=" * 90)

    if by_mode:
        best_mode = max(by_mode.items(), key=lambda x: sum(e.overall_score for e in x[1]) / len(x[1]))
        fastest_mode = min(by_mode.items(), key=lambda x: sum(e.latency_ms for e in x[1]) / len(x[1]))

        print(f"\n🏆 Best quality mode: {best_mode[0].upper()}")
        print(f"⚡ Fastest mode: {fastest_mode[0].upper()}")
        print("\n💡 Use 'baseline' or 'router' for speed")
        print("💡 Use 'crag' or 'agentic' for quality")
        print("💡 'decompose' excels at comparisons")


if __name__ == "__main__":
    main()
