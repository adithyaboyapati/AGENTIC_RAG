"""Canonical verification engine — LLM judge + deterministic citation checks."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.config import settings
from src.contracts.models import Citation, Evidence, VerificationResult
from src.graph.citation_mapper import map_citations, validate_citation_mapping
from src.resilience.node_gate import check_answer

logger = logging.getLogger(__name__)

CITATION_COMPLETENESS_METHOD = "heuristic"


@dataclass(frozen=True)
class VerificationInput:
    question: str
    answer: str
    context_evidence: list[Evidence]
    citations: list[Citation]
    unknown_citation_indexes: list[int]


def _generation_evidence_ids(context_evidence: list[Evidence]) -> tuple[str, ...]:
    return tuple(
        item.evidence_id
        for item in context_evidence
        if item.included_in_context
    )


def _build_generation_context(context_evidence: list[Evidence]) -> str:
    parts: list[str] = []
    for item in context_evidence:
        if not item.included_in_context:
            continue
        marker = item.context_position or item.index
        parts.append(f"[{marker}] {item.content}")
    return "\n\n".join(parts)


def _llm_faithfulness(question: str, answer: str, context: str) -> tuple[float | None, str | None]:
    if not getattr(settings, "canonical_verification_llm_enabled", True):
        return None, "llm_verification_disabled"
    if not context.strip():
        return None, "no_generation_context"
    try:
        from src.evaluation.metrics import faithfulness_chain

        result = faithfulness_chain.invoke(
            {"question": question, "answer": answer, "context": context}
        )
        return float(result.score), None
    except Exception:
        logger.warning("Faithfulness LLM judge failed", exc_info=True)
        return None, "faithfulness_judge_failed"


def _llm_answer_relevance(question: str, answer: str) -> tuple[float | None, str | None]:
    if not getattr(settings, "canonical_verification_llm_enabled", True):
        return None, "llm_verification_disabled"
    try:
        from src.evaluation.metrics import relevance_chain

        result = relevance_chain.invoke({"question": question, "answer": answer})
        return float(result.score), None
    except Exception:
        logger.warning("Answer relevance LLM judge failed", exc_info=True)
        return None, "relevance_judge_failed"


def _assert_verified_evidence_invariant(
    verified_ids: tuple[str, ...],
    generation_ids: tuple[str, ...],
    *,
    evaluation_started: bool,
) -> None:
    if not evaluation_started:
        return
    assert verified_ids == generation_ids, (
        "verified_evidence_ids must equal generation_evidence_ids "
        f"(verified={verified_ids}, generation={generation_ids})"
    )


def verify_response(payload: VerificationInput) -> VerificationResult:
    """Single-pass verification over generation-visible evidence only."""
    generation_ids = _generation_evidence_ids(payload.context_evidence)
    issues: list[str] = []
    evaluation_started = False

    answer_gate = check_answer(payload.answer, required=True)
    if not answer_gate.ok:
        issues.append(answer_gate.message)
        return VerificationResult(
            verified_evidence_ids=(),
            passed=False,
            outcome="FAIL",
            reason="verification aborted before evaluation",
            confidence=0.0,
            faithfulness=0.0,
            answer_relevance=0.0,
            citation_correctness=0.0,
            citation_completeness=0.0,
            abstained=True,
            flagged_reason="; ".join(issues),
            metadata={"citation_completeness_method": CITATION_COMPLETENESS_METHOD},
        )

    evaluation_started = True

    citations = list(payload.citations)
    unknown = list(payload.unknown_citation_indexes)
    duplicate_invalid: list[int] = []
    malformed: list[str] = []
    zero_indexes: list[int] = []

    if not citations and payload.answer.strip():
        mapped, unknown, duplicate_invalid, malformed, zero_indexes = map_citations(
            payload.answer,
            payload.context_evidence,
        )
        citations = mapped

    correctness, completeness, citation_issues, _snippet_mismatches = validate_citation_mapping(
        citations,
        payload.context_evidence,
        unknown,
        malformed_markers=malformed,
        zero_indexes=zero_indexes,
        duplicate_indexes=duplicate_invalid,
    )
    issues.extend(citation_issues)

    context_text = _build_generation_context(payload.context_evidence)
    faithfulness_llm, faith_err = _llm_faithfulness(
        payload.question, payload.answer, context_text
    )
    relevance_llm, rel_err = _llm_answer_relevance(payload.question, payload.answer)
    if faith_err:
        issues.append(faith_err)
    if rel_err:
        issues.append(rel_err)

    faithfulness = faithfulness_llm if faithfulness_llm is not None else correctness
    answer_relevance = relevance_llm if relevance_llm is not None else (1.0 if answer_gate.ok else 0.3)

    faith_min = float(getattr(settings, "canonical_verification_faithfulness_min", 0.5))
    rel_min = float(getattr(settings, "canonical_verification_relevance_min", 0.4))

    if not generation_ids and payload.answer.strip():
        faithfulness = 0.0
        issues.append("answer_without_context")

    confidence = min(
        faithfulness,
        answer_relevance,
        correctness,
        completeness,
    )

    abstained = False
    if faithfulness_llm is not None and faithfulness_llm < faith_min:
        abstained = True
        issues.append(f"faithfulness_below_threshold:{faithfulness_llm:.2f}<{faith_min:.2f}")
    if not generation_ids and payload.answer.strip():
        abstained = True
    if relevance_llm is not None and relevance_llm < rel_min and not generation_ids:
        abstained = True

    if abstained or faithfulness < faith_min or (not generation_ids and payload.answer.strip()):
        outcome = "FAIL"
        passed = False
        abstained = True
    elif issues or correctness < 0.8 or completeness < 0.5:
        outcome = "WARN"
        passed = True
        abstained = False
    else:
        outcome = "PASS"
        passed = True
        abstained = False

    flagged = "; ".join(issues) if issues else None
    warn_conf = float(getattr(settings, "consensus_min_confidence", 0.5))
    if confidence < warn_conf and outcome == "PASS":
        outcome = "WARN"

    result = VerificationResult(
        verified_evidence_ids=generation_ids,
        passed=passed,
        outcome=outcome,
        reason=flagged or "verification complete",
        confidence=round(confidence, 2),
        faithfulness=round(faithfulness, 2),
        answer_relevance=round(answer_relevance, 2),
        citation_correctness=round(correctness, 2),
        citation_completeness=round(completeness, 2),
        abstained=abstained,
        flagged_reason=flagged,
        metadata={"citation_completeness_method": CITATION_COMPLETENESS_METHOD},
    )
    _assert_verified_evidence_invariant(
        result.verified_evidence_ids,
        generation_ids,
        evaluation_started=evaluation_started,
    )
    return result


def derive_response_status(
    verification: VerificationResult | None,
    *,
    error_code: str | None = None,
) -> str:
    if error_code:
        return "abstained"
    if verification is None:
        return "answered"
    if verification.abstained or verification.outcome == "FAIL":
        return "abstained"
    if verification.outcome == "WARN":
        return "answered_with_warning"
    return "answered"


def apply_verification_outcome(answer: str, verification: VerificationResult) -> str:
    if verification.outcome == "FAIL" or verification.abstained:
        return (
            "I don't have sufficient verified evidence to answer this question safely."
        )
    if verification.outcome == "WARN" and verification.flagged_reason:
        return (
            f"{answer.rstrip()}\n\n"
            f"_Verification warning: {verification.flagged_reason}_"
        )
    return answer
