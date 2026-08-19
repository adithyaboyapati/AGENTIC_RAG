"""Tests for Dynamic Context Compression & Selective Token Pruning."""

from langchain_core.documents import Document

from src.config import settings
from src.retrieval.compression import compress_documents, compress_text
from src.retrieval.retriever import format_docs


def test_compress_text_selective_pruning():
    passage = (
        "Retrieval-augmented generation (RAG) combines search with LLMs. "
        "In modern systems, conversational memory is an optional feature. "
        "Corrective RAG (CRAG) achieved a 94.5% accuracy rate on the PopQA benchmark. "
        "The weather today in San Francisco was pleasant and mild. "
        "CRAG evaluates document quality before invoking external web search."
    )

    query = "What accuracy did CRAG achieve on PopQA?"
    compressed, stats = compress_text(passage, query, target_ratio=0.6)

    # Must preserve the query-relevant sentence with numbers and entities
    assert "94.5%" in compressed
    assert "PopQA benchmark" in compressed
    assert "Corrective RAG" in compressed

    # Filler sentence about weather should be pruned
    assert "weather today in San Francisco" not in compressed
    assert stats.savings_pct > 0.0


def test_compress_documents_preserves_tables_and_metadata():
    docs = [
        Document(
            page_content=(
                "LangGraph is used for agent orchestration. "
                "It enables cyclic graphs with conditional branching. "
                "General software engineering is a broad field of study. "
                "State transitions in LangGraph are fully deterministic."
            ),
            metadata={"source": "langgraph.pdf", "page": 2},
        ),
        Document(
            page_content="| Framework | Loops |\n|---|---|\n| LangGraph | Yes |\n| Sequential | No |",
            metadata={"source": "tables.pdf", "page": 5, "chunk_type": "table"},
        ),
    ]

    query = "Does LangGraph support cyclic loops and conditional branching?"
    compressed = compress_documents(query, docs, ratio=0.6)

    assert len(compressed) == 2
    # Table should not be corrupted
    assert "| Framework | Loops |" in compressed[1].page_content
    # Metadata preserved
    assert compressed[0].metadata["source"] == "langgraph.pdf"
    assert compressed[0].metadata.get("compressed") is True


def test_format_docs_with_query_compression():
    docs = [
        Document(
            page_content="CRAG evaluated 10,000 queries. The cafeteria serves lunch at noon. Retrieval score was 0.98.",
            metadata={"source": "benchmarks.pdf", "page": 1, "section_path": "4. Results"},
        )
    ]

    orig_enabled = settings.context_compression_enabled
    settings.context_compression_enabled = True
    try:
        formatted = format_docs(docs, query="What was the retrieval score of CRAG?")
        assert "retrieval score was 0.98" in formatted.lower() or "0.98" in formatted
        assert "benchmarks.pdf" in formatted
        assert "cafeteria serves lunch" not in formatted
    finally:
        settings.context_compression_enabled = orig_enabled
