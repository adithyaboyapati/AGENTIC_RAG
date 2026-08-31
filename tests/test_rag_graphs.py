"""Smoke tests for RAG graphs / grader with mocked LLM and retrieval."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from src.agents.grader import DocumentGrade, GradingResult, grade_documents
from src.graph.agent_graph import build_full_agent_graph, rewrite_node, strategy_condition
from src.graph.consensus_graph import build_consensus_graph
from src.graph.crag_graph import build_crag_graph
from src.graph.decompose_graph import build_decompose_graph
from src.graph.multi_hop_graph import build_multi_hop_graph
from src.graph.router_graph import build_router_graph, generate_node
from src.graph.tools_graph import build_tools_graph
from src.rag.baseline import ask_baseline
from src.retrieval.retriever import EMPTY_RETRIEVAL_MESSAGE


def _edge_pairs(compiled) -> set[tuple[str, str]]:
    return {(e.source, e.target) for e in compiled.get_graph().edges}


def test_graphs_compile():
    builders = [
        build_router_graph,
        build_crag_graph,
        build_decompose_graph,
        build_multi_hop_graph,
        build_tools_graph,
        build_full_agent_graph,
        build_consensus_graph,
    ]
    for build in builders:
        compiled = build()
        assert compiled is not None
        assert compiled.get_graph().nodes


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


def test_ask_baseline_skips_generation_when_empty():
    with patch("src.rag.baseline.retrieve", return_value=[]):
        with patch("src.rag.baseline.stream_text") as mock_stream:
            result = ask_baseline("What is RAG?")
    mock_stream.assert_not_called()
    assert result.answer == EMPTY_RETRIEVAL_MESSAGE
    assert result.context_docs == []


def test_router_generate_skips_empty_documents():
    update = generate_node(
        {
            "question": "What is RAG?",
            "documents": [],
            "route": "retrieve",
            "route_reason": "",
            "web_context": "",
            "answer": "",
            "sources": [],
            "steps": [],
        }
    )
    assert update["answer"] == EMPTY_RETRIEVAL_MESSAGE
    assert "skipped generation" in update["steps"][0]


def test_agentic_edges_route_strategies_through_grade():
    pairs = _edge_pairs(build_full_agent_graph())
    for src in ("decompose", "multi_hop", "tools", "simple_retrieve"):
        assert (src, "grade") in pairs
    assert ("rewrite", "grade") in pairs
    assert ("grade", "generate") in pairs
    assert ("grade", "rewrite") in pairs


def test_rewrite_node_compounds_previous_search_query():
    rewritten = MagicMock()
    rewritten.query = "corrective retrieval augmented generation fallback"
    rewritten.reason = "expanded CRAG"
    docs = [Document(page_content="fallback is web search", metadata={"source": "rag.pdf"})]
    with patch("src.graph.agent_graph.rewrite_query", return_value=rewritten) as mock_rw:
        with patch("src.graph.agent_graph.retrieve", return_value=docs):
            update = rewrite_node(
                {
                    "question": "What fallback does CRAG use?",
                    "search_query": "CRAG fallback",
                    "retry_count": 0,
                    "abort": False,
                }
            )
    mock_rw.assert_called_once_with("What fallback does CRAG use?", "CRAG fallback")
    assert update["search_query"] == rewritten.query
    assert update["retry_count"] == 1
    assert len(update["documents"]) == 1


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
