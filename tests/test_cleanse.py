"""Tests for ingestion cleansing (headers, footers, irrelevant sections)."""

from __future__ import annotations

from langchain_core.documents import Document

from src.config import PROJECT_ROOT
from src.ingestion.cleanse import (
    CleanseConfig,
    cleanse_block_text,
    filter_irrelevant_parents,
    is_irrelevant_section_title,
)
from src.ingestion.chunking import build_toc_parents

PDF = PROJECT_ROOT / "data" / "sample_docs" / "rag.pdf"


def test_hyphenation_join():
    cfg = CleanseConfig(fix_hyphenation=True, drop_headers_footers=False)
    text = cleanse_block_text("The con-\ntained knowledge is useful.", cfg)
    assert "contained" in text
    assert "con-\n" not in text


def test_page_number_and_arxiv_dropped():
    cfg = CleanseConfig()
    text = cleanse_block_text("12\narXiv:2312.10997v5  [cs.CL]  27 Mar 2024\nReal content here.", cfg)
    assert "Real content here" in text
    assert "arXiv" not in text
    assert not text.startswith("12")


def test_boilerplate_email_dropped():
    cfg = CleanseConfig()
    text = cleanse_block_text(
        "Corresponding Author.Email:haofen.wang@tongji.edu.cn\nUseful abstract text.",
        cfg,
    )
    assert "Useful abstract text" in text
    assert "haofen.wang" not in text


def test_irrelevant_section_titles():
    assert is_irrelevant_section_title("References")
    assert is_irrelevant_section_title("ACKNOWLEDGMENTS")
    assert is_irrelevant_section_title("Appendix A")
    assert not is_irrelevant_section_title("Naive RAG")
    assert not is_irrelevant_section_title("Introduction")


def test_filter_irrelevant_parents():
    parents = [
        Document(
            page_content="Intro body " * 10,
            metadata={"section_title": "Introduction", "parent_id": "1"},
        ),
        Document(
            page_content="[1] Some paper",
            metadata={"section_title": "References", "parent_id": "2"},
        ),
    ]
    kept = filter_irrelevant_parents(parents)
    assert len(kept) == 1
    assert kept[0].metadata["section_title"] == "Introduction"


def test_toc_parents_drop_references():
    if not PDF.exists():
        return
    parents = build_toc_parents(PDF)
    titles = {p.metadata["section_title"] for p in parents}
    assert "References" not in titles
    assert any("Naive" in t for t in titles)
    # Page numbers should not dominate cleaned preamble
    preamble = next(p for p in parents if p.metadata["section_title"] == "Preamble / Abstract")
    assert not preamble.page_content.strip().startswith("1\n")
    assert "arXiv" not in preamble.page_content
