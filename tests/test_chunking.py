"""Tests for section-aware parent–child chunking."""

from __future__ import annotations


from langchain_core.documents import Document

from src.config import PROJECT_ROOT
from src.ingestion.chunking import (
    build_regex_parents,
    build_toc_parents,
    chunk_documents,
    parents_to_children,
)
from src.ingestion.parent_store import (
    clear_parents,
    expand_children_to_parents,
    get_parent,
    save_parents,
)

PDF = PROJECT_ROOT / "data" / "sample_docs" / "rag.pdf"


def test_toc_parents_from_rag_survey():
    if not PDF.exists():
        return
    parents = build_toc_parents(PDF)
    assert len(parents) >= 20
    titles = {p.metadata["section_title"] for p in parents}
    assert "Naive RAG" in titles or any("Naive" in t for t in titles)
    assert "Preamble / Abstract" in titles
    assert all(p.metadata.get("parent_id") for p in parents)
    assert all(p.metadata.get("section_path") for p in parents)


def test_parents_to_children_preserve_lineage():
    parents = [
        Document(
            page_content="A" * 1200,
            metadata={
                "source": "x.pdf",
                "page": 1,
                "section_title": "Intro",
                "section_path": "Intro",
                "parent_id": "p1",
                "doc_type": "parent",
            },
        )
    ]
    children = parents_to_children(parents, child_chunk_size=400, child_chunk_overlap=40)
    assert len(children) >= 2
    assert all(c.metadata["parent_id"] == "p1" for c in children)
    assert all(c.metadata["doc_type"] == "child" for c in children)
    assert all(c.page_content.startswith("Section: Intro") for c in children)


def test_expand_children_to_parents_dedupes(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.ingestion.parent_store.parent_store_path",
        lambda: tmp_path / "parents.json",
    )
    monkeypatch.setattr("src.ingestion.parent_store._cache", None)
    clear_parents()

    parent = Document(
        page_content="Full parent section about CRAG.",
        metadata={
            "source": "rag.pdf",
            "page": 2,
            "section_title": "CRAG",
            "section_path": "Retrieval > CRAG",
            "parent_id": "parent-crag",
            "doc_type": "parent",
        },
    )
    save_parents([parent], merge=False)
    assert get_parent("parent-crag") is not None

    children = [
        Document(
            page_content="Section: Retrieval > CRAG\n\nchild A",
            metadata={"parent_id": "parent-crag", "chunk_id": "c1", "score": 0.9},
        ),
        Document(
            page_content="Section: Retrieval > CRAG\n\nchild B",
            metadata={"parent_id": "parent-crag", "chunk_id": "c2", "score": 0.8},
        ),
    ]
    expanded = expand_children_to_parents(children)
    assert len(expanded) == 1
    assert "Full parent section about CRAG" in expanded[0].page_content
    assert expanded[0].metadata["section_title"] == "CRAG"


def test_regex_parents_fallback():
    pages = [
        Document(
            page_content="I. INTRODUCTION\nHello world about RAG.\n\nII. OVERVIEW OF RAG\nMore detail here on paradigms.",
            metadata={"source": "x.pdf", "page": 0},
        )
    ]
    parents = build_regex_parents(pages)
    assert len(parents) >= 2
    assert "INTRODUCTION" in parents[0].metadata["section_title"].upper()


def test_chunk_documents_fixed_strategy():
    pages = [
        Document(page_content="word " * 300, metadata={"source": "a.pdf", "page": 0})
    ]
    children, parents = chunk_documents(
        None,
        pages,
        strategy="fixed",
        chunk_size=200,
        chunk_overlap=20,
    )
    assert parents == []
    assert len(children) >= 2


def test_chunk_documents_section_strategy_on_pdf():
    if not PDF.exists():
        return
    pages = [
        Document(page_content="placeholder", metadata={"source": str(PDF), "page": 0})
    ]
    children, parents = chunk_documents(
        PDF,
        pages,
        strategy="section_parent_child",
        child_chunk_size=500,
        child_chunk_overlap=80,
    )
    assert len(parents) >= 20
    assert len(children) >= len(parents)
    assert all(c.metadata.get("parent_id") for c in children)
