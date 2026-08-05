"""
Phase 4: Query Decomposition.

Uses LangChain structured output to split complex questions into
independent sub-queries for parallel retrieval.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.llm import get_llm
from src.prompts import DECOMPOSE_PROMPT


class DecompositionResult(BaseModel):
    """Structured output: sub-queries for parallel retrieval."""

    sub_queries: list[str] = Field(
        min_length=1,
        max_length=5,
        description="Independent sub-queries to retrieve separately",
    )
    reasoning: str = Field(description="Why the question was decomposed this way")


decompose_chain = DECOMPOSE_PROMPT | get_llm().with_structured_output(DecompositionResult)


def decompose_query(question: str) -> DecompositionResult:
    """Split a question into sub-queries using the LangChain decompose chain."""
    return decompose_chain.invoke({"question": question})
