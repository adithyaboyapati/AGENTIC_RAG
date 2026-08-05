"""Document ingestion: load PDFs with PyMuPDF, chunk, embed, and store in ChromaDB."""

from __future__ import annotations

import argparse
import threading
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from src.config import settings

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


def get_vector_store() -> Chroma:
    """Return a cached Chroma instance (safe for parallel LangGraph workers)."""
    global _vector_store
    if _vector_store is None:
        with _init_lock:
            if _vector_store is None:
                _vector_store = Chroma(
                    collection_name=settings.collection_name,
                    embedding_function=get_embeddings(),
                    persist_directory=settings.chroma_persist_dir,
                )
    return _vector_store


def load_pdfs(source_dir: Path) -> list[Document]:
    """Load all PDF files from source_dir using PyMuPDF."""
    pdf_files = sorted(source_dir.glob("**/*.pdf"))
    if not pdf_files:
        raise ValueError(f"No PDF files found in {source_dir}")

    documents: list[Document] = []
    for pdf_path in pdf_files:
        loader = PyMuPDFLoader(str(pdf_path))
        pages = loader.load()
        documents.extend(pages)
        print(f"Loaded {len(pages)} pages from {pdf_path.name}")

    return documents


def ingest(source_dir: str | Path, chunk_size: int = 1000, chunk_overlap: int = 150) -> int:
    """Load PDFs from source_dir, chunk, embed, and store. Returns chunk count."""
    source = Path(source_dir)
    if not source.exists():
        raise FileNotFoundError(f"Source directory not found: {source}")

    documents = load_pdfs(source)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(documents)

    vector_store = get_vector_store()
    vector_store.add_documents(chunks)

    print(f"Indexed {len(chunks)} chunks from {len(documents)} pages")
    return len(chunks)

def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest PDF documents into ChromaDB")
    parser.add_argument("--source", required=True, help="Directory containing PDF files")
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--chunk-overlap", type=int, default=150)
    args = parser.parse_args()

    ingest(args.source, chunk_size=args.chunk_size, chunk_overlap=args.chunk_overlap)


if __name__ == "__main__":
    main()
