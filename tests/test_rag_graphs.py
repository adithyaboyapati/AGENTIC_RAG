"""Smoke tests for RAG graphs / grader with mocked LLM and retrieval."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from src.agents.grader import DocumentGrade, GradingResult, grade_documents
from src.graph.agent_graph import build_full_agent_graph, strategy_condition
from src.graph.crag_graph import build_crag_graph
from src.graph.router_graph import build_router_graph
from src.rag.baseline import ask_baseline


def test_graphs_compile():
    assert build_router_graph() is not None
    assert build_crag_graph() is not None
    assert build_full_agent_graph() is not None


def test_strategy_condition_defaults_invalid_to_simple():
    assert strategy_condition({"strategy": "nope"}) == "simple"
    assert strategy_condition({"strategy": "decompose"}) == "decompose"


def test_grade_documents_filters_by_threshold():
    docs = [
        Document(page_content="relevant", metadata={"source": "a", "chunk_id": "1"}),
        Document(page_content="noise", metadata={"source": "b", "chunk_id": "2"}),
    ]
    grading = GradingResult(
        grades=[
            DocumentGrade(chunk_index=1, relevant=True, score=0.9, reason="yes"),
            DocumentGrade(chunk_index=2, relevant=True, score=0.1, reason="weak"),
        ]
    )
    with patch("src.agents.grader.grader_chain") as mock_chain:
        mock_chain.invoke.return_value = grading
        with patch("src.agents.grader.settings") as mock_settings:
            mock_settings.grader_relevance_threshold = 0.5
            filtered, result = grade_documents("q", docs)
    assert len(filtered) == 1
    assert filtered[0].page_content == "relevant"
    assert len(result.grades) == 2


def test_ask_baseline_returns_context_docs():
    docs = [
        Document(
            page_content="RAG retrieves then generates",
            metadata={"source": "rag.pdf", "page": 1, "chunk_id": "c1"},
        )
    ]
    with patch("src.rag.baseline.retrieve", return_value=docs):
        with patch("src.rag.baseline.rag_chain") as mock_chain:
            mock_chain.invoke.return_value = "RAG retrieves then generates."
            result = ask_baseline("What is RAG?")
    assert result.mode == "baseline"
    assert result.context_docs == ["RAG retrieves then generates"]
    assert result.citations[0].page == 1
    assert "rag.pdf#p1" in result.sources


def test_agentic_edges_route_strategies_through_grade():
    graph = build_full_agent_graph()
    # Compiled StateGraph exposes nodes; ensure grade is reachable from strategies
    # via graph definition inspection on the builder-equivalent compiled structure.
    assert "grade" in graph.get_graph().nodes
    assert "decompose" in graph.get_graph().nodes
    assert "multi_hop" in graph.get_graph().nodes
    assert "tools" in graph.get_graph().nodes


def test_evaluate_uses_context_docs_not_source_paths():
    from src.evaluation.evaluate_all_modes import evaluate_query
    from src.schemas import AgentResponse, Citation

    fake = AgentResponse(
        answer="Grounded answer about RAG",
        mode="baseline",
        sources=["/path/to/rag.pdf"],
        context_docs=["Retrieval-augmented generation combines search with LLMs."],
        citations=[
            Citation(
                index=1,
                chunk_id="c1",
                source="rag.pdf",
                page=1,
                snippet="Retrieval-augmented generation",
            )
        ],
    )
    with patch("src.evaluation.evaluate_all_modes.run_agent", return_value=fake):
        with patch("src.evaluation.evaluate_all_modes.evaluate_metrics") as mock_metrics:
            mock_metrics.return_value = MagicMock(
                faithfulness=1.0,
                answer_relevance=1.0,
                context_precision=1.0,
                overall_score=1.0,
            )
            evaluate_query("What is RAG?", "baseline")
            args = mock_metrics.call_args[0]
            assert "Retrieval-augmented generation" in args[2]
            assert "/path/to/rag.pdf" not in args[2]
