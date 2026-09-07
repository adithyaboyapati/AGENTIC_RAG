"""Contract tests for canonical Agentic RAG architecture (Phase 1)."""

from __future__ import annotations

import pytest
from langchain_core.documents import Document

from src.contracts.conversions import (
    document_to_retrieval_result,
    evidence_to_citation,
    expand_parent_provenance,
    retrieval_result_to_evidence,
)
from src.contracts.models import (
    Citation,
    Evidence,
    RetrievalResult,
    ScoreBundle,
    ToolResult,
    ToolStatus,
    VerificationResult,
)
from src.contracts.state import CanonicalAgentState
from src.contracts.validation import (
    ContractValidationError,
    validate_canonical_agent_state,
    validate_citation,
    validate_evidence,
    validate_retrieval_result,
    validate_state_transition,
    validate_tool_result,
    validate_verification_result,
)
from src.schemas import RBACContext


def _make_doc(**meta) -> Document:
    defaults = {
        "source": "rag.pdf",
        "page": 1,
        "chunk_id": "chunk-1",
        "score": 0.82,
    }
    defaults.update(meta)
    return Document(page_content="Self-RAG uses reflection tokens.", metadata=defaults)


def _make_result(**overrides) -> RetrievalResult:
    base = document_to_retrieval_result(_make_doc(), query_id="qry_test")
    if overrides:
        return base.model_copy(update=overrides)
    return base


def _make_evidence(result: RetrievalResult | None = None) -> Evidence:
    result = result or _make_result()
    return retrieval_result_to_evidence(result, index=1)


def test_retrieval_result_preserves_all_score_fields():
    doc = Document(
        page_content="hybrid hit",
        metadata={
            "chunk_id": "h1",
            "source": "paper.pdf",
            "dense_score": 0.91,
            "sparse_score": 4.2,
            "fusion_score": 0.016,
            "rerank_score": 0.95,
            "grade_score": 0.88,
            "score": 0.95,
            "retrieval_score": 0.016,
        },
    )
    result = document_to_retrieval_result(doc, query_id="qry_hybrid")

    assert result.scores.dense_score == 0.91
    assert result.scores.sparse_score == 4.2
    assert result.scores.fusion_score == 0.016
    assert result.scores.rerank_score == 0.95
    assert result.scores.grade_score == 0.88


def test_legacy_rerank_metadata_maps_to_separate_scores():
    doc = Document(
        page_content="reranked",
        metadata={
            "chunk_id": "r1",
            "score": 0.95,
            "retrieval_score": 0.12,
            "rerank_score": 0.95,
            "rerank_provider": "flashrank",
        },
    )
    result = document_to_retrieval_result(doc, query_id="qry_rerank")

    assert result.scores.fusion_score == 0.12
    assert result.scores.rerank_score == 0.95
    assert result.scores.dense_score is None


def test_evidence_preserves_retrieval_result_provenance():
    result = _make_result()
    evidence = retrieval_result_to_evidence(result, evidence_id="evd_fixed", index=2)

    assert evidence.evidence_id == "evd_fixed"
    assert evidence.result.result_id == result.result_id
    assert evidence.result.query_id == result.query_id
    assert evidence.index == 2


def test_citation_cannot_reference_unknown_evidence():
    evidence = _make_evidence()
    citation = evidence_to_citation(evidence)
    validate_citation(citation, known_evidence_ids=[evidence.evidence_id])

    bad = Citation(
        evidence_id="evd_missing",
        index=1,
        chunk_id="c1",
        source="x.pdf",
    )
    with pytest.raises(ContractValidationError, match="unknown_evidence_reference"):
        validate_citation(bad, known_evidence_ids=[evidence.evidence_id])


def test_verification_cannot_reference_absent_generation_evidence():
    shown = _make_evidence()
    hidden = retrieval_result_to_evidence(
        _make_result(chunk_id="hidden"),
        evidence_id="evd_hidden",
        shown_to_generation=False,
    )
    verification = VerificationResult(
        verified_evidence_ids=(shown.evidence_id,),
        passed=True,
    )
    validate_verification_result(
        verification,
        generation_evidence_ids=[shown.evidence_id],
    )

    bad = VerificationResult(
        verified_evidence_ids=(hidden.evidence_id,),
        passed=False,
    )
    with pytest.raises(ContractValidationError, match="verification_unknown_evidence"):
        validate_verification_result(
            bad,
            generation_evidence_ids=[shown.evidence_id],
        )


def test_original_question_cannot_be_overwritten():
    rbac = RBACContext(tenant_id="acme", user_roles=["analyst"])
    previous = CanonicalAgentState(
        original_question="What is CRAG?",
        rbac_context=rbac,
    )
    next_state = CanonicalAgentState(
        original_question="Different question",
        rbac_context=rbac,
    )
    with pytest.raises(ContractValidationError, match="immutable_question_mutated"):
        validate_state_transition(previous, next_state)


def test_rbac_context_cannot_change_during_run():
    previous = CanonicalAgentState(
        original_question="What is RAG?",
        rbac_context=RBACContext(tenant_id="acme", user_roles=["analyst"]),
    )
    next_state = CanonicalAgentState(
        original_question="What is RAG?",
        rbac_context=RBACContext(tenant_id="other", user_roles=["analyst"]),
    )
    with pytest.raises(ContractValidationError, match="immutable_rbac_mutated"):
        validate_state_transition(previous, next_state)


def test_tool_result_uses_structured_status_values():
    ok = ToolResult(tool_name="retrieve_docs", status=ToolStatus.SUCCESS, output="found docs")
    validate_tool_result(ok)

    err = ToolResult(
        tool_name="web_search",
        status=ToolStatus.ERROR,
        error_code="timeout",
        output="request timed out",
    )
    validate_tool_result(err)

    with pytest.raises(ContractValidationError, match="missing_tool_error_detail"):
        validate_tool_result(
            ToolResult(tool_name="calc", status=ToolStatus.ERROR, output="", error_code="")
        )


def test_duplicate_evidence_ids_are_rejected():
    result = _make_result()
    evidence_a = retrieval_result_to_evidence(result, evidence_id="evd_dup", index=1)
    evidence_b = retrieval_result_to_evidence(result, evidence_id="evd_dup", index=2)

    seen: set[str] = set()
    validate_evidence(evidence_a, seen_evidence_ids=seen)
    with pytest.raises(ContractValidationError, match="duplicate_evidence_id"):
        validate_evidence(evidence_b, seen_evidence_ids=seen)


def test_invalid_score_values_are_rejected():
    bad = RetrievalResult(
        result_id="res_bad",
        query_id="qry_bad",
        chunk_id="c1",
        content="text",
        scores=ScoreBundle(grade_score=1.5),
    )
    with pytest.raises(ContractValidationError, match="invalid_grade_score"):
        validate_retrieval_result(bad)


def test_parent_expansion_preserves_provenance():
    child_doc = Document(
        page_content="child chunk",
        metadata={
            "chunk_id": "child-1",
            "parent_id": "parent-sec-1",
            "score": 0.77,
            "rerank_score": 0.88,
            "retrieval_score": 0.77,
        },
    )
    parent_doc = Document(
        page_content="Full parent section text.",
        metadata={
            "chunk_id": "parent-sec-1",
            "source": "rag.pdf",
            "section_title": "CRAG",
            "doc_type": "parent",
        },
    )
    child = document_to_retrieval_result(child_doc, query_id="qry_parent", index=1)
    parent = document_to_retrieval_result(parent_doc, query_id="qry_parent", index=1)
    expanded = expand_parent_provenance(child, parent)

    assert expanded.parent_result_id == child.result_id
    assert expanded.matched_child_id == child.chunk_id
    assert expanded.scores.rerank_score == 0.88
    assert expanded.scores.fusion_score == 0.77
    assert expanded.metadata.get("expanded_from_child") is True


def test_canonical_state_validates_end_to_end():
    result = _make_result()
    evidence = retrieval_result_to_evidence(result, index=1)
    citation = evidence_to_citation(evidence)
    state = CanonicalAgentState(
        original_question="What is Self-RAG?",
        rbac_context=RBACContext(tenant_id="default"),
        retrieval_results=(result,),
        evidence=(evidence,),
        generation_evidence_ids=(evidence.evidence_id,),
        citations=(citation,),
        verification=VerificationResult(
            verified_evidence_ids=(evidence.evidence_id,),
            passed=True,
            confidence=0.9,
        ),
    )
    validate_canonical_agent_state(state)


def test_evidence_to_citation_display_score_prefers_rerank():
    doc = Document(
        page_content="content",
        metadata={
            "chunk_id": "s1",
            "score": 0.95,
            "fusion_score": 0.2,
            "rerank_score": 0.95,
        },
    )
    result = document_to_retrieval_result(doc, query_id="qry_score")
    evidence = retrieval_result_to_evidence(result)
    citation = evidence_to_citation(evidence)
    assert citation.display_score == 0.95
