"""
Phase 1: Baseline RAG — fixed LangChain pipeline.

  retriever.invoke() → format_docs → rag_chain.invoke()

Compare with Phase 2+ LangGraph agents to see the difference.
"""

from __future__ import annotations

from src.chains.generation import rag_chain
from src.retrieval.retriever import format_docs, retrieve
from src.schemas import AgentResponse


def ask_baseline(question: str) -> AgentResponse:
    """Naive RAG: always retrieve, always generate. No agentic decisions."""
    docs = retrieve(question)
    context = format_docs(docs)

    answer = rag_chain.invoke({"context": context, "question": question})

    sources = list({doc.metadata.get("source", "unknown") for doc in docs})
    return AgentResponse(
        answer=answer,
        mode="baseline",
        sources=sources,
    )
