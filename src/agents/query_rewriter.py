"""Query rewriter for CRAG retry loop — LangChain structured output."""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.llm import get_llm
from src.prompts import QUERY_REWRITE_PROMPT


class RewrittenQuery(BaseModel):
    """Improved search query after failed retrieval."""

    query: str = Field(description="Rewritten search query for vector retrieval")
    reason: str = Field(description="Why this rewrite should work better")


rewrite_chain = QUERY_REWRITE_PROMPT | get_llm().with_structured_output(RewrittenQuery)


def rewrite_query(question: str, search_query: str) -> RewrittenQuery:
    """Rewrite the search query after irrelevant retrieval."""
    return rewrite_chain.invoke({"question": question, "search_query": search_query})
