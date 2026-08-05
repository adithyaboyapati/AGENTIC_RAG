"""
Phase 2: Query Router — first agentic decision.

Uses LangChain:
  - ChatPromptTemplate (src/prompts.py)
  - with_structured_output (Pydantic)
  - LCEL chain: prompt | llm
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from src.llm import get_llm
from src.prompts import ROUTER_PROMPT


class RouteType(str, Enum):
    DIRECT = "direct"
    RETRIEVE = "retrieve"
    WEB_SEARCH = "web_search"


class RouteDecision(BaseModel):
    """Structured output from the router LLM."""

    route: RouteType = Field(description="The chosen route for this question")
    reason: str = Field(description="Brief explanation of why this route was chosen")


# LangChain LCEL chain: prompt → structured LLM
router_chain = ROUTER_PROMPT | get_llm().with_structured_output(RouteDecision)


def classify_query(question: str) -> RouteDecision:
    """Classify the query using the LangChain router chain."""
    return router_chain.invoke({"question": question})
