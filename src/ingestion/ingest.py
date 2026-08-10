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

    try:
        from src.retrieval.retriever import invalidate_bm25_cache

        invalidate_bm25_cache()
    except Exception:
        pass

    try:
        from src.cache.redis_cache import flush_answer_cache

        flush_answer_cache()
    except Exception:
        logger.debug("Answer cache flush skipped during reset", exc_info=True)


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
    try:
        vector_store.delete(ids=ids)
    except Exception:
        logger.debug("No prior chunk IDs to replace (first ingest or partial overlap)")
    vector_store.add_documents(all_children, ids=ids)

    try:
        from src.retrieval.retriever import invalidate_bm25_cache

        invalidate_bm25_cache()
    except Exception:
        pass

    try:
        from src.cache.redis_cache import flush_answer_cache

        flushed = flush_answer_cache()
        if flushed:
            print(f"Flushed {flushed} cached answer(s) after ingest")
    except Exception:
        logger.debug("Answer cache flush skipped after ingest", exc_info=True)

    print(
        f"Indexed {len(all_children)} child chunks from {total_pages} pages "
        f"({len(all_parents)} parent sections, strategy={strategy})"
    )
    return len(all_children)


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
