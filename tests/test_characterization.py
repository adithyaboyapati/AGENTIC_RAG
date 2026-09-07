"""Characterization tests for retrieval, citations, and shared agent utilities."""

from __future__ import annotations

from unittest.mock import patch

from langchain_core.documents import Document

from src.agents.grader import DocumentGrade, GradingResult, grade_documents, summarize_grades
from src.retrieval.citations import build_response, docs_to_citations, docs_to_sources
from src.retrieval.retriever import _rrf_fuse, format_docs


SAMPLE_DOCS = [
    Document(
        page_content="Corrective RAG grades retrieved chunks and may rewrite the query.",
        metadata={
            "source": "crag.pdf",
            "page": 2,
            "chunk_id": "crag-2",
            "section_title": "CRAG Loop",
            "score": 0.84,
        },
    ),
    Document(
        page_content="Multi-hop retrieval chains dependent sub-queries across hops.",
        metadata={
            "source": "multihop.pdf",
            "page": 5,
            "chunk_id": "mh-5",
            "section_title": "Sequential Hops",
            "score": 0.71,
        },
    ),
]


class TestRetrievalCharacterization:
    def test_rrf_fusion_order_and_score_metadata(self):
        dense = Document(page_content="overlap", metadata={"chunk_id": "shared", "score": 0.9})
        only_dense = Document(page_content="dense only", metadata={"chunk_id": "d-only"})
        only_sparse = Document(page_content="bm25 only", metadata={"chunk_id": "s-only"})
        fused = _rrf_fuse([[dense, only_dense], [dense, only_sparse]], rrf_k=60)

        assert fused[0].metadata["chunk_id"] == "shared"
        assert isinstance(fused[0].metadata["score"], float)
        assert fused[0].metadata["score"] > 0

    def test_format_docs_structure(self):
        text = format_docs(SAMPLE_DOCS[:1])
        assert "[1] Source: crag.pdf, page 2, section=CRAG Loop (crag-2)" in text
        assert "Corrective RAG grades" in text


class TestCitationCharacterization:
    def test_docs_to_citations_fields(self):
        citations = docs_to_citations(SAMPLE_DOCS)
        assert len(citations) == 2
        assert citations[0].index == 1
        assert citations[0].chunk_id == "crag-2"
        assert citations[0].section == "CRAG Loop"
        assert citations[0].score == 0.84
        assert len(citations[0].snippet) <= 300

    def test_docs_to_sources_deduplicates_pages(self):
        sources = docs_to_sources(SAMPLE_DOCS)
        assert sources == ["crag.pdf#p2 [CRAG Loop]", "multihop.pdf#p5 [Sequential Hops]"]

    def test_build_response_shape(self):
        response = build_response(
            answer="CRAG improves retrieval quality.",
            mode="canonical",
            docs=SAMPLE_DOCS[:1],
            grade_summary="1/1 relevant",
        )
        assert response.mode == "canonical"
        assert response.answer.startswith("CRAG")
        assert response.context_docs == [SAMPLE_DOCS[0].page_content]
        assert response.citations[0].chunk_id == "crag-2"
        assert response.sources == ["crag.pdf#p2 [CRAG Loop]"]
        assert response.grade_summary == "1/1 relevant"


class TestGraderCharacterization:
    def test_grade_documents_threshold_filtering(self):
        grading = GradingResult(
            grades=[
                DocumentGrade(chunk_index=1, relevant=True, score=0.92, reason="direct hit"),
                DocumentGrade(chunk_index=2, relevant=True, score=0.2, reason="weak"),
            ]
        )
        with patch("src.agents.grader.grader_chain") as mock_chain:
            mock_chain.invoke.return_value = grading
            with patch("src.agents.grader.settings") as mock_settings:
                mock_settings.grader_relevance_threshold = 0.5
                filtered, result = grade_documents("What is CRAG?", SAMPLE_DOCS)

        assert [doc.metadata["chunk_id"] for doc in filtered] == ["crag-2"]
        assert len(result.grades) == 2
        assert summarize_grades(result) == "1/2 chunks relevant (avg score: 0.56)"
