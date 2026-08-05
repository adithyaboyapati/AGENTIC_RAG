"""
Phase 5: Multi-Hop Retrieval planner and reflector.

Uses LangChain structured output to:
  1. Analyze if multi-hop is needed and plan the first search query
  2. After each hop, reflect on whether to continue or synthesize
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.llm import get_llm
from src.prompts import HOP_REFLECT_PROMPT, MULTI_HOP_ANALYZE_PROMPT


class MultiHopAnalysis(BaseModel):
    """Initial analysis: plan the first retrieval hop."""

    needs_multi_hop: bool = Field(description="True if multiple sequential retrievals are needed")
    first_search_query: str = Field(description="The first search query to run")
    reasoning: str = Field(description="Why this retrieval strategy was chosen")


class HopReflection(BaseModel):
    """Reflection after each hop: continue or stop."""

    sufficient: bool = Field(description="True if enough context exists to answer the original question")
    intermediate_finding: str = Field(description="Key information learned from this hop")
    next_search_query: str | None = Field(
        default=None,
        description="Next search query if more retrieval is needed",
    )


analyze_chain = MULTI_HOP_ANALYZE_PROMPT | get_llm().with_structured_output(MultiHopAnalysis)
reflect_chain = HOP_REFLECT_PROMPT | get_llm().with_structured_output(HopReflection)


def analyze_question(question: str) -> MultiHopAnalysis:
    """Analyze the question and plan the first hop."""
    return analyze_chain.invoke({"question": question})


def reflect_on_hop(
    question: str,
    hop_number: int,
    search_query: str,
    context: str,
    hop_history: str,
) -> HopReflection:
    """Reflect on a completed hop and decide whether to continue."""
    return reflect_chain.invoke(
        {
            "question": question,
            "hop_number": hop_number,
            "search_query": search_query,
            "context": context,
            "hop_history": hop_history or "None yet",
        }
    )
