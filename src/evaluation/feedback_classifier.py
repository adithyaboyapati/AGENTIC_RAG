"""Map user feedback to failure categories for regression triage (Phase 8)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

FAILURE_CATEGORIES = frozenset(
    {
        "retrieval_failure",
        "generation_failure",
        "citation_failure",
        "hallucination",
        "wrong_abstention",
        "irrelevant_answer",
        "security_issue",
        "unknown",
    }
)

_USER_CATEGORY_MAP: dict[str, str] = {
    "hallucination": "hallucination",
    "wrong_source": "citation_failure",
    "incomplete": "generation_failure",
    "off_topic": "irrelevant_answer",
    "too_slow": "unknown",
    "formatting": "generation_failure",
    "other": "unknown",
}


class FailureCategory(str, Enum):
    RETRIEVAL_FAILURE = "retrieval_failure"
    GENERATION_FAILURE = "generation_failure"
    CITATION_FAILURE = "citation_failure"
    HALLUCINATION = "hallucination"
    WRONG_ABSTENTION = "wrong_abstention"
    IRRELEVANT_ANSWER = "irrelevant_answer"
    SECURITY_ISSUE = "security_issue"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ClassifiedFeedback:
    failure_category: str
    confidence: float
    mapped_from: list[str]
    requires_review: bool


def classify_feedback(record: dict[str, Any]) -> ClassifiedFeedback:
    """Classify feedback into a regression failure category."""
    categories = [str(c) for c in (record.get("categories") or [])]
    rating = str(record.get("rating") or "")
    comment = str(record.get("comment") or "").lower()

    if rating != "down":
        return ClassifiedFeedback("unknown", 0.0, [], False)

    mapped: list[str] = []
    for cat in categories:
        target = _USER_CATEGORY_MAP.get(cat)
        if target:
            mapped.append(target)

    if "security" in comment or "injection" in comment or "unauthorized" in comment:
        return ClassifiedFeedback("security_issue", 0.85, mapped, True)

    if "abstain" in comment or "refused" in comment or "wouldn't answer" in comment:
        return ClassifiedFeedback("wrong_abstention", 0.75, mapped, True)

    if "no sources" in comment or "couldn't find" in comment or "not in documents" in comment:
        return ClassifiedFeedback("retrieval_failure", 0.7, mapped, True)

    if mapped:
        primary = mapped[0]
        return ClassifiedFeedback(primary, 0.8, mapped, True)

    return ClassifiedFeedback("unknown", 0.4, mapped, True)
