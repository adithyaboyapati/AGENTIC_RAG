"""Runtime validation for canonical contracts and state transitions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from src.contracts.models import (
    Citation,
    Evidence,
    RetrievalResult,
    ToolResult,
    ToolStatus,
    VerificationResult,
)
from src.contracts.state import CanonicalAgentState
from src.schemas import RBACContext


@dataclass(frozen=True)
class ContractValidationError(Exception):
    """Raised when a contract or state invariant is violated."""

    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise ContractValidationError(code, message)


def _is_finite_score(value: float | None, *, allow_negative: bool = False) -> bool:
    if value is None:
        return True
    if value != value:  # NaN
        return False
    if not allow_negative and value < 0:
        return False
    return True


def _validate_score_bundle(result: RetrievalResult) -> None:
    scores = result.scores
    _require(
        _is_finite_score(scores.dense_score),
        "invalid_dense_score",
        f"dense_score must be a finite non-negative float for result_id={result.result_id}",
    )
    _require(
        _is_finite_score(scores.sparse_score, allow_negative=True),
        "invalid_sparse_score",
        f"sparse_score must be finite for result_id={result.result_id}",
    )
    _require(
        _is_finite_score(scores.fusion_score),
        "invalid_fusion_score",
        f"fusion_score must be a finite non-negative float for result_id={result.result_id}",
    )
    _require(
        _is_finite_score(scores.rerank_score, allow_negative=True),
        "invalid_rerank_score",
        f"rerank_score must be finite for result_id={result.result_id}",
    )
    if scores.grade_score is not None:
        _require(
            0.0 <= scores.grade_score <= 1.0,
            "invalid_grade_score",
            f"grade_score must be in [0, 1] for result_id={result.result_id}",
        )


def validate_retrieval_result(result: RetrievalResult) -> None:
    """Validate a single RetrievalResult."""
    _require(bool(result.result_id), "missing_result_id", "RetrievalResult.result_id is required")
    _require(bool(result.query_id), "missing_query_id", "RetrievalResult.query_id is required")
    _require(bool(result.chunk_id), "missing_chunk_id", "RetrievalResult.chunk_id is required")
    _require(
        bool(result.tenant_id.strip()),
        "missing_tenant",
        f"RetrievalResult.tenant_id is required for result_id={result.result_id}",
    )
    _validate_score_bundle(result)


def validate_evidence(
    evidence: Evidence,
    *,
    known_result_ids: Iterable[str] | None = None,
    require_unique_id: bool = True,
    seen_evidence_ids: set[str] | None = None,
) -> None:
    """Validate Evidence and its provenance link to RetrievalResult."""
    _require(
        bool(evidence.evidence_id),
        "missing_evidence_id",
        "Evidence.evidence_id is required",
    )
    if require_unique_id and seen_evidence_ids is not None:
        _require(
            evidence.evidence_id not in seen_evidence_ids,
            "duplicate_evidence_id",
            f"Duplicate evidence_id={evidence.evidence_id!r}",
        )
        seen_evidence_ids.add(evidence.evidence_id)

    validate_retrieval_result(evidence.result)
    _require(
        evidence.result.result_id,
        "broken_provenance",
        "Evidence.result.result_id must be present",
    )


def validate_citation(
    citation: Citation,
    *,
    known_evidence_ids: Iterable[str],
) -> None:
    """Validate Citation and its link to known Evidence."""
    _require(
        bool(citation.evidence_id),
        "missing_evidence_id",
        "Citation.evidence_id is required",
    )
    known = set(known_evidence_ids)
    _require(
        citation.evidence_id in known,
        "unknown_evidence_reference",
        f"Citation references unknown evidence_id={citation.evidence_id!r}",
    )
    _require(bool(citation.chunk_id), "missing_chunk_id", "Citation.chunk_id is required")
    if citation.display_score is not None:
        _require(
            citation.display_score == citation.display_score,
            "invalid_display_score",
            f"Citation display_score must be finite for evidence_id={citation.evidence_id}",
        )


def validate_tool_result(result: ToolResult) -> None:
    """Validate structured ToolResult status values."""
    _require(bool(result.tool_name), "missing_tool_name", "ToolResult.tool_name is required")
    _require(
        isinstance(result.status, ToolStatus),
        "invalid_tool_status",
        f"ToolResult.status must be a ToolStatus enum, got {result.status!r}",
    )
    if result.status in {ToolStatus.ERROR, ToolStatus.CIRCUIT_OPEN, ToolStatus.QUARANTINE}:
        _require(
            bool((result.error_code or "").strip()) or bool(result.output.strip()),
            "missing_tool_error_detail",
            f"ToolResult with status={result.status.value} requires error_code or output",
        )


def validate_verification_result(
    verification: VerificationResult,
    *,
    generation_evidence_ids: Iterable[str],
) -> None:
    """Validate verification references only evidence shown to generation."""
    generation_ids = set(generation_evidence_ids)
    for evidence_id in verification.verified_evidence_ids:
        _require(
            evidence_id in generation_ids,
            "verification_unknown_evidence",
            (
                f"Verification references evidence_id={evidence_id!r} "
                "not present in generation context"
            ),
        )


def validate_canonical_agent_state(state: CanonicalAgentState) -> None:
    """Validate a full CanonicalAgentState snapshot."""
    _require(
        bool(state.original_question.strip()),
        "missing_original_question",
        "original_question is required",
    )
    _require(
        bool(state.rbac_context.tenant_id.strip()),
        "missing_tenant",
        "rbac_context.tenant_id is required",
    )

    seen_result_ids: set[str] = set()
    for result in state.retrieval_results:
        validate_retrieval_result(result)
        _require(
            result.result_id not in seen_result_ids,
            "duplicate_result_id",
            f"Duplicate retrieval result_id={result.result_id!r}",
        )
        seen_result_ids.add(result.result_id)

    seen_evidence_ids: set[str] = set()
    for item in state.evidence:
        validate_evidence(item, seen_evidence_ids=seen_evidence_ids)

    known_evidence_ids = {item.evidence_id for item in state.evidence}
    for citation in state.citations:
        validate_citation(citation, known_evidence_ids=known_evidence_ids)

    for tool_result in state.tool_results:
        validate_tool_result(tool_result)

    generation_ids = set(state.generation_evidence_ids)
    shown_ids = {item.evidence_id for item in state.evidence if item.shown_to_generation}
    _require(
        generation_ids <= shown_ids,
        "generation_unknown_evidence",
        "generation_evidence_ids must be a subset of shown evidence",
    )

    if state.verification is not None:
        validate_verification_result(
            state.verification,
            generation_evidence_ids=generation_ids,
        )

    if state.retrieval_plan is not None:
        _require(
            state.retrieval_plan.tenant_id == state.rbac_context.tenant_id,
            "plan_tenant_mismatch",
            "RetrievalPlan.tenant_id must match rbac_context.tenant_id",
        )


def validate_state_transition(
    previous: CanonicalAgentState,
    next_state: CanonicalAgentState,
) -> None:
    """Detect illegal mutations of immutable fields across a state transition."""
    validate_canonical_agent_state(next_state)

    _require(
        next_state.original_question == previous.original_question,
        "immutable_question_mutated",
        "original_question cannot be modified during a run",
    )
    _require(
        _rbac_equal(previous.rbac_context, next_state.rbac_context),
        "immutable_rbac_mutated",
        "rbac_context cannot change during a run",
    )

    prev_result_ids = previous.retrieval_result_ids
    next_result_ids = next_state.retrieval_result_ids
    _require(
        prev_result_ids <= next_result_ids,
        "retrieval_result_id_removed",
        "retrieval result IDs cannot be removed once assigned",
    )

    prev_evidence_ids = previous.evidence_ids
    next_evidence_ids = next_state.evidence_ids
    _require(
        prev_evidence_ids <= next_evidence_ids,
        "evidence_id_removed",
        "evidence IDs cannot be removed once assigned",
    )


def _rbac_equal(left: RBACContext, right: RBACContext) -> bool:
    return (
        left.tenant_id == right.tenant_id
        and left.classification == right.classification
        and sorted(left.user_roles) == sorted(right.user_roles)
    )
