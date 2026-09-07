"""Document ingestion: load PDFs, section-aware parent–child chunk, embed, store."""

from __future__ import annotations

import argparse
import hashlib
import logging
import threading
from pathlib import Path

from langchain_chroma import Chroma
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from src.config import settings
from src.ingestion.chunking import chunk_documents
from src.ingestion.parent_store import clear_parents, invalidate_cache, save_parents

logger = logging.getLogger(__name__)

_vector_store: Chroma | None = None
_embeddings: OpenAIEmbeddings | None = None
# RLock: get_vector_store() initializes embeddings while holding the lock
_init_lock = threading.RLock()


def get_embeddings() -> OpenAIEmbeddings:
    global _embeddings
    if _embeddings is None:
        with _init_lock:
            if _embeddings is None:
                _embeddings = OpenAIEmbeddings(
                    model=settings.openai_embedding_model,
                    api_key=settings.openai_api_key or None,
                )
    return _embeddings


def _chroma_mode() -> str:
    return (settings.chroma_mode or "persistent").strip().lower()


def _chroma_client():
    """Return a raw chromadb client for the configured mode."""
    mode = _chroma_mode()
    if mode == "http":
        from chromadb import HttpClient

        return HttpClient(
            host=settings.chroma_host,
            port=int(settings.chroma_port),
            ssl=bool(settings.chroma_ssl),
        )
    from chromadb import PersistentClient

    return PersistentClient(path=settings.chroma_persist_dir)


def get_vector_store() -> Chroma:
    """Return a cached Chroma instance (safe for parallel LangGraph workers)."""
    global _vector_store
    if _vector_store is None:
        with _init_lock:
            if _vector_store is None:
                mode = _chroma_mode()
                if mode == "http":
                    logger.info(
                        "Connecting to Chroma HTTP %s:%s",
                        settings.chroma_host,
                        settings.chroma_port,
                    )
                    _vector_store = Chroma(
                        collection_name=settings.collection_name,
                        embedding_function=get_embeddings(),
                        client=_chroma_client(),
                    )
                else:
                    _vector_store = Chroma(
                        collection_name=settings.collection_name,
                        embedding_function=get_embeddings(),
                        persist_directory=settings.chroma_persist_dir,
                    )
    return _vector_store


def reset_collection() -> None:
    """Delete the configured Chroma collection and clear parent store / singletons."""
    global _vector_store
    with _init_lock:
        try:
            client = _chroma_client()
            existing = {c.name for c in client.list_collections()}
            if settings.collection_name in existing:
                client.delete_collection(settings.collection_name)
                logger.info("Deleted Chroma collection %s", settings.collection_name)
        except Exception:
            logger.exception("Failed to delete Chroma collection; recreating store anyway")
        _vector_store = None

    clear_parents()
    invalidate_cache()

    _invalidate_retrieval_caches()


def _invalidate_retrieval_caches() -> None:
    """Drop BM25, exact-answer, and semantic caches after the index changes."""
    try:
        from src.retrieval.retriever import invalidate_bm25_cache

        invalidate_bm25_cache()
    except Exception:
        logger.warning("BM25 cache invalidate failed", exc_info=True)
    try:
        from src.cache.redis_cache import flush_answer_cache

        flushed = flush_answer_cache()
        if flushed:
            logger.info("Flushed %d cached answer(s) after index change", flushed)
    except Exception:
        logger.warning("Answer cache flush failed", exc_info=True)
    try:
        from src.cache.semantic_cache import get_semantic_cache

        cleared = get_semantic_cache().clear()
        if cleared:
            logger.info("Cleared %d semantic-cache entries after index change", cleared)
    except Exception:
        logger.warning("Semantic cache clear failed", exc_info=True)


def delete_chunks_for_source(source: str) -> int:
    """Remove previously indexed chunks for a source path so edits cannot orphan."""
    store = get_vector_store()
    deleted = 0
    try:
        collection = store._collection  # noqa: SLF001
        before = collection.count()
        collection.delete(where={"source": str(source)})
        after = collection.count()
        deleted = max(0, before - after)
        if deleted:
            logger.info("Deleted %d stale chunk(s) for source=%s", deleted, source)
    except Exception:
        logger.warning("Source-level delete failed for %s", source, exc_info=True)
    return deleted


def remove_indexed_source(source: str) -> int:
    """Delete a source by path and basename, then drop retrieval caches."""
    if not (source or "").strip():
        return 0
    deleted = delete_chunks_for_source(source)
    name = Path(source).name
    if name and name != source:
        deleted += delete_chunks_for_source(name)
    _invalidate_retrieval_caches()
    return deleted


def list_indexed_documents() -> list[dict]:
    """Aggregate unique sources currently in the vector store."""
    store = get_vector_store()
    try:
        raw = store.get(include=["metadatas"])
    except Exception:
        logger.exception("Failed to list indexed documents")
        return []

    by_source: dict[str, dict] = {}
    for meta in raw.get("metadatas") or []:
        meta = meta or {}
        source = str(meta.get("source") or "unknown")
        entry = by_source.setdefault(
            source,
            {
                "source": source,
                "filename": Path(source).name or source,
                "chunk_count": 0,
                "tenant_id": str(meta.get("tenant_id") or "default"),
                "pages": set(),
            },
        )
        entry["chunk_count"] += 1
        page = meta.get("page")
        if page is not None:
            try:
                entry["pages"].add(int(page))
            except (TypeError, ValueError):
                pass

    documents: list[dict] = []
    for entry in by_source.values():
        pages = sorted(entry["pages"])
        documents.append(
            {
                "source": entry["source"],
                "filename": entry["filename"],
                "chunk_count": entry["chunk_count"],
                "tenant_id": entry["tenant_id"],
                "page_count": len(pages) if pages else None,
            }
        )
    documents.sort(key=lambda d: d["filename"].lower())
    return documents


def chunk_content_id(doc: Document) -> str:
    """Stable content-hash ID for idempotent upserts."""
    existing = doc.metadata.get("chunk_id")
    if existing:
        return str(existing)
    source = str(doc.metadata.get("source", ""))
    page = str(doc.metadata.get("page", ""))
    parent_id = str(doc.metadata.get("parent_id", ""))
    payload = f"{source}|{page}|{parent_id}|{doc.page_content}".encode()
    return hashlib.sha256(payload).hexdigest()


def load_pdfs(source_dir: Path) -> list[tuple[Path, list[Document]]]:
    """Load all PDF files; return (path, page Documents) pairs."""
    pdf_files = sorted(source_dir.glob("**/*.pdf"))
    if not pdf_files:
        raise ValueError(f"No PDF files found in {source_dir}")

    loaded: list[tuple[Path, list[Document]]] = []
    for pdf_path in pdf_files:
        loader = PyMuPDFLoader(str(pdf_path))
        pages = loader.load()
        loaded.append((pdf_path, pages))
        print(f"Loaded {len(pages)} pages from {pdf_path.name}")

    return loaded


def ingest(
    source_dir: str | Path,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    *,
    child_chunk_size: int | None = None,
    child_chunk_overlap: int | None = None,
    strategy: str | None = None,
    reset: bool = False,
    tenant_id: str = "default",
    access_groups: list[str] | None = None,
) -> int:
    """Load PDFs, chunk (section parent–child by default), embed, upsert.

    Returns the number of child chunks indexed.
    """
    source = Path(source_dir)
    if not source.exists():
        raise FileNotFoundError(f"Source directory not found: {source}")

    if reset:
        reset_collection()

    loaded = load_pdfs(source)
    strategy = (strategy or settings.chunking_strategy).lower().strip()

    all_children: list[Document] = []
    all_parents: list[Document] = []
    total_pages = 0

    for pdf_path, pages in loaded:
        total_pages += len(pages)
        children, parents = chunk_documents(
            pdf_path,
            pages,
            strategy=strategy,
            child_chunk_size=child_chunk_size,
            child_chunk_overlap=child_chunk_overlap,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        # Tag tenant and RBAC metadata
        groups_str = ",".join(access_groups or ["public"])
        for c in children:
            c.metadata["tenant_id"] = tenant_id or "default"
            c.metadata["access_groups"] = groups_str
        for p in parents:
            p.metadata["tenant_id"] = tenant_id or "default"
            p.metadata["access_groups"] = groups_str

        all_children.extend(children)
        all_parents.extend(parents)
        print(
            f"  {pdf_path.name}: strategy={strategy} → "
            f"{len(parents)} parent sections, {len(children)} child chunks"
        )

    if all_parents:
        save_parents(all_parents, merge=not reset)

    ids: list[str] = []
    for chunk in all_children:
        cid = chunk_content_id(chunk)
        chunk.metadata["chunk_id"] = cid
        # Chroma metadata values must be scalar
        for key in list(chunk.metadata.keys()):
            value = chunk.metadata[key]
            if isinstance(value, (str, int, float, bool)) or value is None:
                if value is None:
                    del chunk.metadata[key]
                continue
            chunk.metadata[key] = str(value)
        ids.append(cid)

    vector_store = get_vector_store()
    for pdf_path, _pages in loaded:
        delete_chunks_for_source(str(pdf_path))
        delete_chunks_for_source(pdf_path.name)
    try:
        vector_store.delete(ids=ids)
    except Exception:
        logger.debug("No prior chunk IDs to replace (first ingest or partial overlap)")
    vector_store.add_documents(all_children, ids=ids)

    _invalidate_retrieval_caches()

    print(
        f"Indexed {len(all_children)} child chunks from {total_pages} pages "
        f"({len(all_parents)} parent sections, strategy={strategy})"
    )
    try:
        from src.ingestion.document_registry import register_document_ingest

        for pdf_path, _pages in loaded:
            source_chunks = sum(1 for c in all_children if str(c.metadata.get("source", "")).endswith(pdf_path.name))
            register_document_ingest(
                source=str(pdf_path),
                filename=pdf_path.name,
                chunk_count=source_chunks or len(all_children) // max(1, len(loaded)),
                tenant_id=tenant_id or "default",
            )
    except Exception:
        logger.debug("Document registry update skipped", exc_info=True)
    return len(all_children)


def ingest_documents(
    source_path: Path | str,
    tenant_id: str = "default",
    access_groups: list[str] | None = None,
    reset: bool = False,
) -> int:
    """Ingest documents from a file or folder with tenant isolation."""
    p = Path(source_path)
    if not p.exists():
        raise FileNotFoundError(f"Path does not exist: {p}")

    if p.is_file():
        # Single file ingestion
        loader = PyMuPDFLoader(str(p))
        pages = loader.load()
        strategy = settings.chunking_strategy.lower().strip()
        children, parents = chunk_documents(p, pages, strategy=strategy)

        groups_str = ",".join(access_groups or ["public"])
        for c in children:
            c.metadata["tenant_id"] = tenant_id or "default"
            c.metadata["access_groups"] = groups_str
        for pr in parents:
            pr.metadata["tenant_id"] = tenant_id or "default"
            pr.metadata["access_groups"] = groups_str

        if parents:
            save_parents(parents, merge=True)

        ids: list[str] = []
        for chunk in children:
            cid = chunk_content_id(chunk)
            chunk.metadata["chunk_id"] = cid
            for key in list(chunk.metadata.keys()):
                value = chunk.metadata[key]
                if isinstance(value, (str, int, float, bool)) or value is None:
                    if value is None:
                        del chunk.metadata[key]
                    continue
                chunk.metadata[key] = str(value)
            ids.append(cid)

        store = get_vector_store()
        delete_chunks_for_source(str(p))
        try:
            store.delete(ids=ids)
        except Exception:
            pass
        store.add_documents(children, ids=ids)
        _invalidate_retrieval_caches()
        return len(children)

    return ingest(
        p,
        tenant_id=tenant_id,
        access_groups=access_groups,
        reset=reset,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest PDF documents into ChromaDB (section-aware parent–child by default)"
    )
    parser.add_argument("--source", required=True, help="Directory containing PDF files")
    parser.add_argument(
        "--strategy",
        choices=["section_parent_child", "fixed"],
        default=None,
        help="Chunking strategy (default from CHUNKING_STRATEGY)",
    )
    parser.add_argument("--chunk-size", type=int, default=None, help="Fixed strategy size")
    parser.add_argument("--chunk-overlap", type=int, default=None, help="Fixed strategy overlap")
    parser.add_argument("--child-chunk-size", type=int, default=None)
    parser.add_argument("--child-chunk-overlap", type=int, default=None)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the existing collection + parent store before ingesting",
    )
    args = parser.parse_args()

    ingest(
        args.source,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        child_chunk_size=args.child_chunk_size,
        child_chunk_overlap=args.child_chunk_overlap,
        strategy=args.strategy,
        reset=args.reset,
    )


if __name__ == "__main__":
    main()
