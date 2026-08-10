"""
Phase 1: Baseline RAG — fixed LangChain pipeline.

  retriever.invoke() → format_docs → rag_chain.invoke()

Compare with Phase 2+ LangGraph agents to see the difference.
"""

from __future__ import annotations

from src.chains.generation import rag_chain
from src.retrieval.citations import build_response
from src.retrieval.retriever import format_docs, retrieve
from src.schemas import AgentResponse
from src.streaming import emit_step, stream_text


def ask_baseline(question: str) -> AgentResponse:
    """Naive RAG: always retrieve, always generate. No agentic decisions."""
    docs = retrieve(question)
    context = format_docs(docs)
    emit_step(f"Retrieved {len(docs)} chunks")

    answer = stream_text(rag_chain, {"context": context, "question": question})
    emit_step("Generated answer from retrieved context")

    return build_response(
        answer=answer,
        mode="baseline",
        docs=docs,
        steps=[f"Retrieved {len(docs)} chunks", "Generated answer from retrieved context"],
    )
