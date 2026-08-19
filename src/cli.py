"""
CLI for testing each phase of the Agentic RAG learning project.

Modes:
  baseline  — Phase 1: naive RAG
  router    — Phase 2: query routing (LangGraph)
  crag      — Phase 3: corrective RAG (LangGraph loop)
  decompose — Phase 4: query decomposition (LangGraph map-reduce)
  multi_hop — Phase 5: sequential multi-hop retrieval (LangGraph loop)
  tools     — Phase 6: tool-augmented agent (function calling)
  agentic   — Phase 7: full agentic RAG (orchestrator)
  consensus — Phase 8: multi-agent debate (retrieve → propose → challenge → judge)
"""

from __future__ import annotations

import src.bootstrap  # noqa: F401 — enable LangSmith before LangChain imports

import argparse
import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from src.observability import init_langsmith_tracing

console = Console()


def run_query(question: str, mode: str, verbose: bool = False) -> None:
    from src.guardrails import RateLimitError
    from src.runner import run_agent

    try:
        result = run_agent(question, mode)
    except (ValueError, RateLimitError) as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)

    if verbose:
        if result.route:
            console.print(
                Panel(
                    f"Route: [bold]{result.route}[/bold]\nReason: {result.route_reason}",
                    title="Router Decision",
                    border_style="cyan",
                )
            )
        if result.decomposition_reason and result.mode == "decompose":
            sub_q_text = "\n".join(f"  {i}. {q}" for i, q in enumerate(result.sub_queries or [], 1))
            console.print(
                Panel(
                    f"{result.decomposition_reason}\n\nSub-queries:\n{sub_q_text}",
                    title="Decomposition",
                    border_style="magenta",
                )
            )
        if result.decomposition_reason and result.mode == "multi_hop":
            hop_text = "\n".join(f"  Hop {i}: {q}" for i, q in enumerate(result.sub_queries or [], 1))
            console.print(
                Panel(
                    f"{result.decomposition_reason}\n\nRetrieval hops:\n{hop_text}",
                    title="Multi-Hop Plan",
                    border_style="magenta",
                )
            )
        if result.grade_summary:
            console.print(
                Panel(result.grade_summary, title="Grader Summary", border_style="yellow")
            )
        if result.consensus_score is not None:
            critique = result.critique_summary or "—"
            console.print(
                Panel(
                    f"Confidence: [bold]{result.consensus_score:.2f}[/bold]\n"
                    f"Critique: {critique}",
                    title="Consensus",
                    border_style="green",
                )
            )
        if result.steps:
            console.print(
                Panel("\n".join(f"• {step}" for step in result.steps), title="Agent Steps", border_style="blue")
            )
        if result.sources:
            console.print(Panel("\n".join(result.sources), title="Sources", border_style="dim"))

    console.print(Panel(Markdown(result.answer), title=f"Answer ({result.mode})", border_style="green"))


def main() -> None:
    from src.logging_config import setup_logging
    from src.runner import MODE_LABELS

    setup_logging()
    init_langsmith_tracing()

    parser = argparse.ArgumentParser(description="Agentic RAG Research Assistant CLI")
    parser.add_argument("command", choices=["ask"], help="Command to run")
    parser.add_argument("question", help="Your question")
    parser.add_argument(
        "--mode",
        default="baseline",
        choices=list(MODE_LABELS),
        help="RAG mode (see docs/ROADMAP.md)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Show sources and agent steps")
    args = parser.parse_args()

    if args.command == "ask":
        run_query(args.question, args.mode, verbose=args.verbose)


if __name__ == "__main__":
    main()
