"""Unit and invariant tests for the canonical Agentic RAG graph."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document

from src.agents.router import RouteType
from src.contracts.conversions import document_to_retrieval_result, retrieval_result_to_evidence
from src.contracts.models import Evidence
from src.contracts.validation import ContractValidationError, validate_state_transition
from src.graph.canonical_graph import build_canonical_graph, classify_node, rewrite_node
from src.graph.canonical_state import init_canonical_state, merge_state, read_graph_state
from src.graph.citation_mapper import extract_citation_indexes, map_citations
from src.graph.context_builder import fit_context_budget
from src.graph.evidence_management import deduplicate_evidence
from src.graph.strategy_heuristics import heuristic_strategy, select_strategy
from src.graph.verification_engine import VerificationInput, verify_response
from src.retrieval.canonical_adapter import build_retrieval_plan, retrieve_candidates
from src.schemas import RBACContext


@pytest.fixture(autouse=True)
def disable_llm_verification(monkeypatch):
    monkeypatch.setattr(
        "src.config.settings.canonical_verification_llm_enabled",
        False,
    )


def _evidence(**overrides) -> Evidence:
    result = document_to_retrieval_result(
        Document(page_content="RAG combines retrieval with generation.", metadata={"chunk_id": "c1"}),
        query_id="qry_test",
    )
    base = retrieval_result_to_evidence(result, index=1, shown_to_generation=False)
    if overrides:
        return base.model_copy(update=overrides)
    return base


class TestStateInitialization:
    def test_init_populates_required_fields(self):
        state = init_canonical_state("What is RAG?", rbac_context=RBACContext(tenant_id="acme"))
        assert state.original_question == "What is RAG?"
        assert state.rbac_context.tenant_id == "acme"
        assert state.retry_count == 0
        assert state.abort is False
        assert len(state.trace) == 1
        assert state.trace[0].event_type == "request_started"

    def test_question_immutable(self):
        state = init_canonical_state("What is RAG?")
        with pytest.raises(ValueError, match="immutable"):
            merge_state(state, original_question="Changed")


class TestStrategyHeuristics:
    def test_compare_question_selects_decompose(self):
        decision = heuristic_strategy("Compare naive RAG vs agentic RAG")
        assert decision.strategy == "decompose"
        assert decision.decision_source == "heuristic"

    def test_llm_fallback_on_low_confidence(self):
        with patch("src.graph.strategy_heuristics.choose_strategy") as mock_llm:
            mock_llm.return_value = MagicMock(strategy="multi_hop", reasoning="needs hops")
            decision = select_strategy("Tell me something ambiguous and complex enough please")
        assert decision.decision_source == "llm"

    def test_strategy_failure_defaults_simple(self):
        with patch("src.graph.strategy_heuristics.choose_strategy", side_effect=RuntimeError("fail")):
            decision = select_strategy("ambiguous enough query for low confidence path")
        assert decision.strategy == "simple"


class TestRetrievalAdapter:
    def test_retrieval_preserves_scores(self):
        doc = Document(
            page_content="text",
            metadata={
                "chunk_id": "x1",
                "dense_score": 0.8,
                "fusion_score": 0.2,
                "rerank_score": 0.95,
                "tenant_id": "acme",
            },
        )
        with patch("src.retrieval.canonical_adapter.retrieve", return_value=[doc]):
            results = retrieve_candidates("q", query_id="qry1", rbac_context=RBACContext(tenant_id="acme"))
        assert results[0].scores.dense_score == 0.8
        assert results[0].scores.rerank_score == 0.95

    def test_build_simple_plan(self):
        plan = build_retrieval_plan(
            original_question="What is RAG?",
            strategy="simple",
            rbac_context=RBACContext(),
        )
        assert len(plan.queries) == 1
        assert plan.original_question == "What is RAG?"


class TestEvidenceManagement:
    def test_deduplicate_evidence(self):
        a = _evidence()
        b = _evidence()
        assert len(deduplicate_evidence([a, b])) == 1

    def test_token_budget_exclusion(self):
        long = _evidence(content="word " * 5000)
        included, excluded = fit_context_budget(
            [long],
            budget=type("B", (), {"available_context_tokens": 50})(),
        )
        assert not included
        assert excluded[0].excluded_reason == "token_budget"


class TestCitations:
    def test_extract_citation_indexes(self):
        assert extract_citation_indexes("RAG is useful [1] and proven [2].") == [1, 2]

    def test_map_citations_rejects_unknown(self):
        ev = _evidence(included_in_context=True, context_position=1, shown_to_generation=True)
        citations, unknown, _dup, _malformed, _zero = map_citations("Answer [1] and [9]", [ev])
        assert len(citations) == 1
        assert unknown == [9]


class TestVerification:
    def test_verification_only_uses_generation_evidence(self):
        shown = _evidence(included_in_context=True, context_position=1, shown_to_generation=True)
        hidden = _evidence(evidence_id="evd_hidden", included_in_context=False, shown_to_generation=False)
        result = verify_response(
            VerificationInput(
                question="What is RAG?",
                answer="A sufficiently long grounded answer about RAG.",
                context_evidence=[shown],
                citations=[],
                unknown_citation_indexes=[],
            )
        )
        assert shown.evidence_id in result.verified_evidence_ids
        assert hidden.evidence_id not in result.verified_evidence_ids


class TestCanonicalNodes:
    def test_classify_fallback_to_retrieve(self):
        state = init_canonical_state("What is RAG?")
        with patch("src.graph.canonical_graph.invoke_router", side_effect=RuntimeError("router down")):
            update = classify_node({"canonical": state.model_dump(mode="json"), "trace_delta": []})
        parsed = read_graph_state(update)
        assert parsed.route == RouteType.RETRIEVE.value

    def test_rewrite_does_not_call_retriever(self):
        state = merge_state(
            init_canonical_state("Q"),
            search_query="old query",
            retry_count=0,
        )
        with patch("src.graph.canonical_graph.rewrite_query") as mock_rw:
            mock_rw.return_value = MagicMock(query="new query", reason="broader")
            with patch("src.retrieval.canonical_adapter.retrieve") as mock_ret:
                update = rewrite_node({"canonical": state.model_dump(mode="json"), "trace_delta": []})
        mock_ret.assert_not_called()
        parsed = read_graph_state(update)
        assert parsed.metadata.get("next_planned_query") == "new query"


class TestInvariants:
    def test_rbac_immutable_across_transition(self):
        prev = init_canonical_state("Q", rbac_context=RBACContext(tenant_id="a"))
        nxt = merge_state(prev, route="retrieve")
        validate_state_transition(prev, nxt)

    def test_rbac_change_rejected(self):
        prev = init_canonical_state("Q", rbac_context=RBACContext(tenant_id="a"))
        nxt = prev.model_copy(update={"rbac_context": RBACContext(tenant_id="b")})
        with pytest.raises(ContractValidationError, match="immutable_rbac"):
            validate_state_transition(prev, nxt)


class TestGraphCompile:
    def test_canonical_graph_compiles(self):
        compiled = build_canonical_graph()
        assert compiled is not None
        assert compiled.get_graph().nodes
