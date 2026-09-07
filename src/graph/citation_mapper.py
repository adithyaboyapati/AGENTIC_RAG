"""Deterministic citation extraction and mapping for canonical generation."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.contracts.conversions import evidence_to_citation
from src.contracts.models import Citation, Evidence

_CITATION_MARKER_RE = re.compile(r"\[(\d+)\]")
_MALFORMED_MARKER_RE = re.compile(r"\[[^\]]+\]")


@dataclass
class CitationExtraction:
    citations: list[Citation]
    unknown_indexes: list[int]
    duplicate_invalid: list[int]
    malformed_markers: list[str]
    invalid_zero_indexes: list[int]
    snippet_mismatches: list[int]


def extract_citation_indexes(answer: str) -> list[int]:
    return [int(match) for match in _CITATION_MARKER_RE.findall(answer or "")]


def scan_citation_markers(answer: str) -> tuple[list[int], list[str], list[int]]:
    """Return (valid_indexes, malformed_markers, zero_or_negative_indexes)."""
    text = answer or ""
    valid = extract_citation_indexes(text)
    zero_or_negative: list[int] = []
    for match in _CITATION_MARKER_RE.finditer(text):
        value = int(match.group(1))
        if value <= 0:
            zero_or_negative.append(value)

    numeric_spans = {m.span() for m in _CITATION_MARKER_RE.finditer(text)}
    malformed: list[str] = []
    for match in _MALFORMED_MARKER_RE.finditer(text):
        if match.span() not in numeric_spans:
            malformed.append(match.group(0))
    return valid, malformed, zero_or_negative


def _snippet_from_evidence(evidence: Evidence, limit: int = 300) -> str:
    return evidence.content[:limit]


def _snippet_matches(citation: Citation, evidence: Evidence) -> bool:
    if not citation.snippet.strip():
        return True
    hay = evidence.content.lower()
    needle = citation.snippet.strip().lower()
    return needle in hay


def map_citations(
    answer: str,
    context_evidence: list[Evidence],
) -> tuple[list[Citation], list[int], list[int], list[str], list[int]]:
    """Map [n] markers in the answer to Evidence-derived Citations."""
    position_map = {
        item.context_position: item
        for item in context_evidence
        if item.included_in_context and item.context_position is not None
    }
    indexes, malformed, zero_indexes = scan_citation_markers(answer)
    seen: set[int] = set()
    citations: list[Citation] = []
    unknown: list[int] = []
    duplicate_invalid: list[int] = []

    for raw_index in indexes:
        if raw_index <= 0:
            continue
        if raw_index in seen:
            duplicate_invalid.append(raw_index)
            continue
        seen.add(raw_index)
        evidence = position_map.get(raw_index)
        if evidence is None:
            unknown.append(raw_index)
            continue
        citations.append(evidence_to_citation(evidence))

    return citations, unknown, duplicate_invalid, malformed, zero_indexes


def validate_citation_mapping(
    citations: list[Citation],
    context_evidence: list[Evidence],
    unknown_indexes: list[int],
    *,
    malformed_markers: list[str] | None = None,
    zero_indexes: list[int] | None = None,
    duplicate_indexes: list[int] | None = None,
) -> tuple[float, float, list[str], list[int]]:
    """Return citation_correctness, citation_completeness, issues, snippet_mismatches."""
    included = [e for e in context_evidence if e.included_in_context]
    known_ids = {item.evidence_id for item in included}
    position_map = {
        item.context_position: item
        for item in included
        if item.context_position is not None
    }
    issues: list[str] = []
    snippet_mismatches: list[int] = []

    if malformed_markers:
        issues.append(f"malformed_markers={malformed_markers}")
    if zero_indexes:
        issues.append(f"invalid_zero_indexes={zero_indexes}")
    if duplicate_indexes:
        issues.append(f"duplicate_indexes={duplicate_indexes}")
    if unknown_indexes:
        issues.append(f"unknown_indexes={unknown_indexes}")

    invalid = [c for c in citations if c.evidence_id not in known_ids]
    if invalid:
        issues.append(f"invalid_evidence_refs={len(invalid)}")

    for citation in citations:
        evidence = next((e for e in included if e.evidence_id == citation.evidence_id), None)
        if evidence is None:
            continue
        expected_position = evidence.context_position
        if expected_position is not None and citation.index != expected_position:
            issues.append(
                f"index_mismatch:citation={citation.index},evidence={expected_position}"
            )
        if not _snippet_matches(citation, evidence):
            snippet_mismatches.append(citation.index)
            issues.append(f"snippet_mismatch={citation.index}")

    penalty = (
        len(malformed_markers or [])
        + len(zero_indexes or [])
        + len(duplicate_indexes or [])
        + len(unknown_indexes)
        + len(invalid)
        + len(snippet_mismatches)
    )
    denominator = max(1, len(citations) + len(unknown_indexes) + len(malformed_markers or []))
    correctness = max(0.0, 1.0 - penalty / denominator)

    expected = len(included)
    if expected == 0:
        completeness = 1.0 if not citations else min(1.0, len(citations) / max(1, expected))
    else:
        # Heuristic: fraction of context evidence cited at least once.
        cited_positions = {c.index for c in citations}
        referenced = sum(
            1 for e in included if e.context_position in cited_positions
        )
        completeness = referenced / expected

    return correctness, min(1.0, completeness), issues, snippet_mismatches
