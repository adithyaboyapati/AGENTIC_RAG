"""Production failure → regression candidate pipeline (Phase 8)."""

from __future__ import annotations

import logging
import re
from typing import Any

from src.evaluation.dataset_store import EvalCase, save_case
from src.evaluation.feedback_classifier import classify_feedback
from src.privacy import DataRedactor, PIIDetector, get_privacy_policy

logger = logging.getLogger(__name__)

_SENSITIVE_PATTERNS = (
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN-like
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
)


def _sanitize_text(text: str, *, max_len: int = 4000) -> str:
    value = (text or "")[:max_len]
    try:
        policy = get_privacy_policy()
        if policy.output_mode.value != "off":
            findings = PIIDetector.detect_all(value)
            if findings:
                value = DataRedactor._apply(value, findings)
    except Exception:
        pass
    for pattern in _SENSITIVE_PATTERNS:
        value = pattern.sub("[REDACTED]", value)
    return value


def create_regression_candidate_from_feedback(record: dict[str, Any]) -> EvalCase | None:
    """Convert negative feedback into a sanitized regression candidate (requires review)."""
    if str(record.get("rating") or "") != "down":
        return None

    classified = classify_feedback(record)
    case = EvalCase(
        question=_sanitize_text(str(record.get("question") or "")),
        status="candidate",
        rejected_answer=_sanitize_text(str(record.get("answer") or ""), max_len=8000),
        failure_category=classified.failure_category,
        source_event="user_feedback",
        feedback_id=str(record.get("id") or ""),
        request_id=record.get("request_id"),
        tenant_id=str(record.get("tenant_id") or "default"),
        notes=(
            f"Auto-classified from feedback; requires human review before promotion. "
            f"mapped={classified.mapped_from}; confidence={classified.confidence:.2f}"
        ),
    )
    save_case(case)
    logger.info(
        "Regression candidate created | case_id=%s | category=%s | feedback_id=%s",
        case.case_id,
        case.failure_category,
        case.feedback_id,
    )
    return case


def create_regression_candidate_from_observation(
    *,
    question: str,
    failure_category: str,
    source_event: str,
    request_id: str | None = None,
    tenant_id: str = "default",
    rejected_answer: str = "",
    notes: str = "",
) -> EvalCase:
    """Create a regression candidate from a production failure signal."""
    case = EvalCase(
        question=_sanitize_text(question),
        status="candidate",
        rejected_answer=_sanitize_text(rejected_answer, max_len=8000),
        failure_category=failure_category if failure_category in {
            "retrieval_failure",
            "generation_failure",
            "citation_failure",
            "hallucination",
            "wrong_abstention",
            "irrelevant_answer",
            "security_issue",
            "unknown",
        } else "unknown",
        source_event=source_event,
        request_id=request_id,
        tenant_id=tenant_id,
        notes=notes or "Auto-created from production observation; requires review.",
    )
    save_case(case)
    return case
