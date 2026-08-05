"""
Phase 7: Full Agentic RAG Orchestrator.

This agent analyzes each question and picks the best retrieval/tool strategy:
  - decompose? (parallel sub-queries for comparisons)
  - multi_hop? (sequential hops)
  - tools? (function calling for mixed modality)
  - simple? (single-pass retrieval)

Then wraps with CRAG grading for safety.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.llm import get_llm
from src.prompts import ChatPromptTemplate


class StrategyChoice(BaseModel):
    """Analyze question to pick best retrieval strategy."""

    strategy: str = Field(
        description="Strategy choice: 'decompose' (comparisons), 'multi_hop' (sequential), 'tools' (mixed), or 'simple' (direct retrieval)"
    )
    reasoning: str = Field(description="Why this strategy was chosen")


STRATEGY_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You analyze questions to pick the best retrieval strategy for an agentic RAG system.

Strategies:
1. decompose — Use when the question has comparisons ("Compare X vs Y") or multiple distinct entities.
   → Splits into parallel sub-queries, retrieves separately, synthesizes.
   
2. multi_hop — Use when answering requires finding something first, then searching for details about it.
   → Example: "What fallback does CRAG use?" → first learn CRAG, then find fallback.
   → Sequential hops where each depends on the previous.
   
3. tools — Use when the question mixes retrieval with math, web search, or needs function calling.
   → Example: "What is Self-RAG and what is 20*30?" → needs both retrieval and calculator.
   
4. simple — Use for straightforward factual questions about a single topic.
   → Single retrieval pass, grade, and generate.

Choose ONE strategy based on the question structure.""",
        ),
        ("human", "Analyze this question and pick a strategy:\n\n{question}"),
    ]
)

strategy_chain = STRATEGY_PROMPT | get_llm().with_structured_output(StrategyChoice)


def choose_strategy(question: str) -> StrategyChoice:
    """Analyze the question and recommend a retrieval strategy."""
    return strategy_chain.invoke({"question": question})
