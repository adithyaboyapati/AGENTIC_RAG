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
from src.schemas import RBACContext

EMPTY_RETRIEVAL_MESSAGE = (
    "I couldn't find relevant documents in the knowledge base for this question."
)

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


def _filter_rbac(docs: list[Document], rbac_context: RBACContext | None) -> list[Document]:
    """Filter candidate documents based on tenant and role access permissions."""
    if not docs or rbac_context is None:
        return docs
    filtered: list[Document] = []
    for doc in docs:
        t_id = doc.metadata.get("tenant_id")
        a_groups = doc.metadata.get("access_groups") or doc.metadata.get("allowed_roles")
        c_level = doc.metadata.get("classification")
        if rbac_context.is_authorized(t_id, a_groups, c_level):
            filtered.append(doc)
    return filtered


def _dense_retrieve(
    query: str,
    candidate_k: int,
    search_type: str,
    rbac_context: RBACContext | None = None,
) -> list[Document]:
    store = get_vector_store()
    # Over-fetch if RBAC is active so post-filtering still yields sufficient candidates
    fetch_k = candidate_k * 2 if rbac_context is not None else candidate_k

    if search_type == "mmr":
        docs = store.max_marginal_relevance_search(
            query,
            k=fetch_k,
            fetch_k=max(fetch_k, settings.retrieval_candidate_k),
            lambda_mult=settings.retrieval_mmr_lambda,
        )
        return _filter_rbac(docs, rbac_context)[:candidate_k]

    try:
        pairs = store.similarity_search_with_relevance_scores(query, k=fetch_k)
        docs: list[Document] = []
        for doc, score in pairs:
            meta = dict(doc.metadata)
            meta["score"] = float(score)
            docs.append(Document(page_content=doc.page_content, metadata=meta))
        return _filter_rbac(docs, rbac_context)[:candidate_k]
    except Exception:
        docs = store.similarity_search(query, k=fetch_k)
        return _filter_rbac(docs, rbac_context)[:candidate_k]


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


def _attach_extra_sources(
    query: str,
    docs: list[Document],
    include_extra: bool | None,
) -> list[Document]:
    """Prepend database / API / MCP hits when multi-source retrieval is on."""
    use_extra = settings.multi_source_enabled if include_extra is None else include_extra
    if not use_extra:
        return docs
    from src.sources.federation import merge_with_pdf, search_extra_sources

    extra = search_extra_sources(query)
    return merge_with_pdf(docs, extra)


def retrieve(
    query: str,
    top_k: int | None = None,
    rbac_context: RBACContext | None = None,
    include_extra: bool | None = None,
) -> list[Document]:
    """Retrieve → (optional) rerank → top_k, optionally expanding to parent sections.

    Pipeline:
      1. Over-fetch ``candidate_k`` via hybrid / MMR / similarity with RBAC filtering
      2. Cross-encoder rerank (FlashRank) when ``RERANK_ENABLED``
      3. Keep ``top_k`` (or a larger pool when parent-expanding)
      4. Optional parent-section expansion
      5. Optional extra sources (SQLite catalog, sample API, lab MCP)
    """
    from src.schemas import RBACContext

    ctx = rbac_context or RBACContext()
    final_k = top_k or settings.retrieval_top_k
    candidate_k = max(final_k, settings.retrieval_candidate_k)
    mode = (settings.retrieval_search_type or "similarity").lower()

    # Keep extra children when parent-expanding so dedupe still fills final_k
    pool_k = max(final_k * 3, final_k) if settings.expand_to_parent else final_k

    if mode == "hybrid":
        dense_docs = _dense_retrieve(query, candidate_k, "similarity", ctx)
        bm25 = _get_bm25_retriever(candidate_k)
        sparse_docs = bm25.invoke(query) if bm25 is not None else []
        sparse_docs = _filter_rbac(sparse_docs, ctx)
        candidates = _rrf_fuse([dense_docs, sparse_docs], settings.retrieval_rrf_k)[
            :candidate_k
        ]
        mode_label = "hybrid"
    elif mode == "mmr":
        candidates = _dense_retrieve(query, candidate_k, "mmr", ctx)
        mode_label = "mmr"
    else:
        candidates = _dense_retrieve(query, candidate_k, "similarity", ctx)
        mode_label = "similarity"

    if settings.rerank_enabled:
        docs = rerank_documents(query, candidates, top_n=pool_k)
        mode_label = f"{mode_label}+rerank"
    else:
        docs = candidates[:pool_k]

    if settings.expand_to_parent:
        from src.ingestion.parent_store import expand_children_to_parents

        expanded = expand_children_to_parents(docs)[:final_k]
        expanded = _filter_rbac(expanded, ctx)
        before_extra = expanded
        expanded = _attach_extra_sources(query, expanded, include_extra)
        extra_bit = "+sources" if expanded is not before_extra else ""
        _log_retrieval(query, expanded, f"{mode_label}+parent{extra_bit}")
        return expanded

    docs = docs[:final_k]
    merged = _attach_extra_sources(query, docs, include_extra)
    extra_bit = "+sources" if merged is not docs else ""
    _log_retrieval(query, merged, f"{mode_label}{extra_bit}")
    return merged


def format_docs(docs: list[Document], query: str | None = None) -> str:
    """Format retrieved documents for prompt context (section + page + multimodal tags)."""
    if not docs:
        return ""

    if query and settings.context_compression_enabled:
        try:
            from src.retrieval.compression import compress_documents

            docs = compress_documents(query, docs)
        except Exception:
            logger.debug("Context compression failed in format_docs", exc_info=True)

    parts = []
    for i, doc in enumerate(docs, 1):
        source = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page")
        page_bit = f", page {page}" if page is not None else ""
        section = doc.metadata.get("section_path") or doc.metadata.get("section_title")
        section_bit = f", section={section}" if section else ""
        chunk_id = doc.metadata.get("chunk_id") or doc.metadata.get("id")
        id_bit = f" ({chunk_id})" if chunk_id else ""
        chunk_type = doc.metadata.get("chunk_type")
        source_type = (doc.metadata.get("source_type") or "").lower()
        if source_type in ("database", "api", "mcp"):
            type_bit = f" [{source_type.upper()}]"
        elif chunk_type in ("table", "figure"):
            type_bit = f" [{chunk_type.upper()}]"
        else:
            type_bit = ""

        parts.append(
            f"[{i}] Source: {source}{page_bit}{section_bit}{type_bit}{id_bit}\n{doc.page_content}"
        )
    return "\n\n---\n\n".join(parts)


def invalidate_bm25_cache() -> None:
    """Call after ingest/reset so BM25 rebuilds on next retrieve."""
    global _bm25_retriever, _bm25_doc_count
    with _bm25_lock:
        _bm25_retriever = None
        _bm25_doc_count = None
