"""Vector retrieval using LangChain VectorStoreRetriever."""

from __future__ import annotations

import threading

from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStoreRetriever

from src.config import settings
from src.ingestion.ingest import get_vector_store

_retriever: VectorStoreRetriever | None = None
# Lock guards singleton construction only. Chroma queries are safe to run
# concurrently — serializing every retrieval would defeat the parallel
# sub-query retrieval in the decompose graph.
_init_lock = threading.Lock()


def get_retriever() -> VectorStoreRetriever:
    """LangChain retriever backed by ChromaDB (cached singleton)."""
    global _retriever
    if _retriever is None:
        with _init_lock:
            if _retriever is None:
                _retriever = get_vector_store().as_retriever(
                    search_type="similarity",
                    search_kwargs={"k": settings.retrieval_top_k},
                )
    return _retriever


def retrieve(query: str, top_k: int | None = None) -> list[Document]:
    """Retrieve documents for a query (safe for parallel graph workers)."""
    if top_k is not None:
        retriever = get_vector_store().as_retriever(search_kwargs={"k": top_k})
        return retriever.invoke(query)
    return get_retriever().invoke(query)


def format_docs(docs: list[Document]) -> str:
    """Format retrieved documents for prompt context."""
    parts = []
    for i, doc in enumerate(docs, 1):
        source = doc.metadata.get("source", "unknown")
        parts.append(f"[{i}] Source: {source}\n{doc.page_content}")
    return "\n\n---\n\n".join(parts)
