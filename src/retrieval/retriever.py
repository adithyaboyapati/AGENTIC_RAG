"""Vector retrieval with over-fetch, hybrid (dense+BM25), MMR, rerank, and logging."""

from __future__ import annotations

import logging
import threading
from collections import defaultdict

from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStoreRetriever

from src.config import settings
from src.ingestion.ingest import get_vector_store
from src.retrieval.reranker import rerank_documents

logger = logging.getLogger(__name__)

_bm25_lock = threading.Lock()
_bm25_retriever = None
_bm25_doc_count: int | None = None


def get_retriever(top_k: int | None = None) -> VectorStoreRetriever:
    """LangChain retriever backed by ChromaDB (not cached — k is request-scoped)."""
    k = top_k or settings.retrieval_top_k
    search_type = settings.retrieval_search_type
    if search_type == "hybrid":
        search_type = "similarity"
    kwargs: dict = {"k": k}
    if search_type == "mmr":
        kwargs["fetch_k"] = max(k, settings.retrieval_candidate_k)
        kwargs["lambda_mult"] = settings.retrieval_mmr_lambda
    return get_vector_store().as_retriever(
        search_type=search_type if search_type in ("similarity", "mmr") else "similarity",
        search_kwargs=kwargs,
    )


def _collection_count() -> int:
    store = get_vector_store()
    try:
        return store._collection.count()  # noqa: SLF001 — chroma client
    except Exception:
        return 0


def _load_corpus_documents() -> list[Document]:
    store = get_vector_store()
    raw = store.get(include=["documents", "metadatas"])
    docs: list[Document] = []
    ids = raw.get("ids") or []
    documents = raw.get("documents") or []
    metadatas = raw.get("metadatas") or []
    for i, content in enumerate(documents):
        if not content:
            continue
        meta = dict(metadatas[i] or {})
        if ids and i < len(ids) and "chunk_id" not in meta:
            meta["chunk_id"] = ids[i]
        docs.append(Document(page_content=content, metadata=meta))
    return docs


def _get_bm25_retriever(candidate_k: int):
    """Lazy BM25 index over the Chroma corpus (rebuilt when count changes)."""
    global _bm25_retriever, _bm25_doc_count
    count = _collection_count()
    with _bm25_lock:
        if _bm25_retriever is not None and _bm25_doc_count == count:
            _bm25_retriever.k = candidate_k
            return _bm25_retriever

        from langchain_community.retrievers import BM25Retriever

        corpus = _load_corpus_documents()
        if not corpus:
            _bm25_retriever = None
            _bm25_doc_count = count
            return None

        retriever = BM25Retriever.from_documents(corpus)
        retriever.k = candidate_k
        _bm25_retriever = retriever
        _bm25_doc_count = count
        logger.info("Built BM25 index over %d chunks", len(corpus))
        return _bm25_retriever


def _doc_key(doc: Document) -> str:
    chunk_id = doc.metadata.get("chunk_id") or doc.metadata.get("id")
    if chunk_id:
        return str(chunk_id)
    source = doc.metadata.get("source", "")
    page = doc.metadata.get("page", "")
    return f"{source}|{page}|{hash(doc.page_content)}"


def _rrf_fuse(ranked_lists: list[list[Document]], rrf_k: int) -> list[Document]:
    scores: dict[str, float] = defaultdict(float)
    by_key: dict[str, Document] = {}
    for ranked in ranked_lists:
        for rank, doc in enumerate(ranked):
            key = _doc_key(doc)
            scores[key] += 1.0 / (rrf_k + rank + 1)
            if key not in by_key:
                by_key[key] = doc
            else:
                # Prefer metadata that already carries a dense score
                if "score" not in by_key[key].metadata and "score" in doc.metadata:
                    by_key[key] = doc

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    fused: list[Document] = []
    for key, score in ordered:
        doc = by_key[key]
        meta = dict(doc.metadata)
        meta["score"] = float(score)
        fused.append(Document(page_content=doc.page_content, metadata=meta))
    return fused


def _dense_retrieve(query: str, candidate_k: int, search_type: str) -> list[Document]:
    store = get_vector_store()
    if search_type == "mmr":
        docs = store.max_marginal_relevance_search(
            query,
            k=candidate_k,
            fetch_k=max(candidate_k, settings.retrieval_candidate_k),
            lambda_mult=settings.retrieval_mmr_lambda,
        )
        return docs

    try:
        pairs = store.similarity_search_with_relevance_scores(query, k=candidate_k)
        docs: list[Document] = []
        for doc, score in pairs:
            meta = dict(doc.metadata)
            meta["score"] = float(score)
            docs.append(Document(page_content=doc.page_content, metadata=meta))
        return docs
    except Exception:
        return store.similarity_search(query, k=candidate_k)


def _log_retrieval(query: str, docs: list[Document], mode: str) -> None:
    if not docs:
        logger.info("retrieval | mode=%s | query=%r | hits=0", mode, query[:120])
        return
    details = []
    for i, doc in enumerate(docs, 1):
        chunk_id = doc.metadata.get("chunk_id") or doc.metadata.get("id") or f"idx-{i}"
        score = doc.metadata.get("score")
        page = doc.metadata.get("page")
        details.append(f"{chunk_id}:score={score}:page={page}")
    logger.info(
        "retrieval | mode=%s | query=%r | hits=%d | %s",
        mode,
        query[:120],
        len(docs),
        " | ".join(details),
    )


def retrieve(query: str, top_k: int | None = None) -> list[Document]:
    """Retrieve → (optional) rerank → top_k, optionally expanding to parent sections.

    Pipeline:
      1. Over-fetch ``candidate_k`` via hybrid / MMR / similarity
      2. Cross-encoder rerank (FlashRank) when ``RERANK_ENABLED``
      3. Keep ``top_k`` (or a larger pool when parent-expanding)
      4. Optional parent-section expansion
    """
    final_k = top_k or settings.retrieval_top_k
    candidate_k = max(final_k, settings.retrieval_candidate_k)
    mode = (settings.retrieval_search_type or "similarity").lower()

    # Keep extra children when parent-expanding so dedupe still fills final_k
    pool_k = max(final_k * 3, final_k) if settings.expand_to_parent else final_k

    if mode == "hybrid":
        dense_docs = _dense_retrieve(query, candidate_k, "similarity")
        bm25 = _get_bm25_retriever(candidate_k)
        sparse_docs = bm25.invoke(query) if bm25 is not None else []
        candidates = _rrf_fuse([dense_docs, sparse_docs], settings.retrieval_rrf_k)[
            :candidate_k
        ]
        mode_label = "hybrid"
    elif mode == "mmr":
        candidates = _dense_retrieve(query, candidate_k, "mmr")
        mode_label = "mmr"
    else:
        candidates = _dense_retrieve(query, candidate_k, "similarity")
        mode_label = "similarity"

    if settings.rerank_enabled:
        docs = rerank_documents(query, candidates, top_n=pool_k)
        mode_label = f"{mode_label}+rerank"
    else:
        docs = candidates[:pool_k]

    if settings.expand_to_parent:
        from src.ingestion.parent_store import expand_children_to_parents

        expanded = expand_children_to_parents(docs)[:final_k]
        _log_retrieval(query, expanded, f"{mode_label}+parent")
        return expanded

    docs = docs[:final_k]
    _log_retrieval(query, docs, mode_label)
    return docs


def format_docs(docs: list[Document]) -> str:
    """Format retrieved documents for prompt context (section + page when present)."""
    parts = []
    for i, doc in enumerate(docs, 1):
        source = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page")
        page_bit = f", page {page}" if page is not None else ""
        section = doc.metadata.get("section_path") or doc.metadata.get("section_title")
        section_bit = f", section={section}" if section else ""
        chunk_id = doc.metadata.get("chunk_id") or doc.metadata.get("id")
        id_bit = f" ({chunk_id})" if chunk_id else ""
        parts.append(
            f"[{i}] Source: {source}{page_bit}{section_bit}{id_bit}\n{doc.page_content}"
        )
    return "\n\n---\n\n".join(parts)


def invalidate_bm25_cache() -> None:
    """Call after ingest/reset so BM25 rebuilds on next retrieve."""
    global _bm25_retriever, _bm25_doc_count
    with _bm25_lock:
        _bm25_retriever = None
        _bm25_doc_count = None
