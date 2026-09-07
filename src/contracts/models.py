"""Canonical data contracts for the Agentic RAG architecture."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ScoreBundle(BaseModel):
    """Retrieval scores kept in separate, non-overwriting fields."""

    model_config = ConfigDict(frozen=True)

    dense_score: float | None = None
    sparse_score: float | None = None
    fusion_score: float | None = None
    rerank_score: float | None = None
    grade_score: float | None = None

    @field_validator(
        "dense_score",
        "sparse_score",
        "fusion_score",
        "rerank_score",
        "grade_score",
        mode="before",
    )
    @classmethod
    def _coerce_optional_float(cls, value: Any) -> float | None:
        if value is None:
            return None
        return float(value)


class PlannedQuery(BaseModel):
    """A single planned retrieval query within a broader plan."""

    model_config = ConfigDict(frozen=True)

    query_id: str = Field(default_factory=lambda: _new_id("qry"))
    text: str = Field(min_length=1)
    purpose: str = "primary"
    hop_index: int | None = None
    parent_query_id: str | None = None

    @field_validator("text")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query text must not be empty")
        return stripped


class RetrievalPlan(BaseModel):
    """Ordered set of planned queries for one retrieval episode."""

    model_config = ConfigDict(frozen=True)

    plan_id: str = Field(default_factory=lambda: _new_id("plan"))
    original_question: str = Field(min_length=1)
    queries: tuple[PlannedQuery, ...] = Field(min_length=1)
    tenant_id: str = "default"
    top_k: int = Field(default=5, ge=1)
    strategy: str | None = None

    @field_validator("original_question")
    @classmethod
    def _strip_question(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("original_question must not be empty")
        return stripped

    @model_validator(mode="after")
    def _validate_query_ids_unique(self) -> RetrievalPlan:
        ids = [query.query_id for query in self.queries]
        if len(ids) != len(set(ids)):
            raise ValueError("PlannedQuery.query_id values must be unique within a plan")
        return self


class RetrievalResult(BaseModel):
    """One retrieved chunk with explicit provenance and score preservation."""

    model_config = ConfigDict(frozen=True)

    result_id: str = Field(default_factory=lambda: _new_id("res"))
    query_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    content: str
    source: str = "unknown"
    page: int | None = None
    section: str | None = None
    tenant_id: str = "default"
    scores: ScoreBundle = Field(default_factory=ScoreBundle)
    metadata: dict[str, Any] = Field(default_factory=dict)
    parent_result_id: str | None = None
    matched_child_id: str | None = None

    @field_validator("content", mode="before")
    @classmethod
    def _coerce_content(cls, value: Any) -> str:
        return "" if value is None else str(value)


class Evidence(BaseModel):
    """Evidence unit derived from a retrieval result, ready for generation."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str = Field(default_factory=lambda: _new_id("evd"))
    result: RetrievalResult
    content: str
    shown_to_generation: bool = True
    index: int = Field(ge=1)
    included_in_context: bool = False
    context_position: int | None = Field(default=None, ge=1)
    excluded_reason: str | None = None

    @model_validator(mode="after")
    def _content_non_empty_when_shown(self) -> Evidence:
        if self.shown_to_generation and self.included_in_context and not self.content.strip():
            raise ValueError("Evidence included in context must have non-empty content")
        return self


class Citation(BaseModel):
    """Chunk-level provenance linked to evidence."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str = Field(min_length=1)
    index: int = Field(ge=1)
    chunk_id: str = Field(min_length=1)
    source: str = "unknown"
    page: int | None = None
    section: str | None = None
    snippet: str = ""
    display_score: float | None = None

    def label(self) -> str:
        label = self.source
        if self.page is not None:
            label = f"{label}#p{self.page}"
        if self.section:
            label = f"{label} [{self.section}]"
        return label


class ToolStatus(str, Enum):
    """Structured tool execution status."""

    SUCCESS = "success"
    EMPTY = "empty"
    ERROR = "error"
    CIRCUIT_OPEN = "circuit_open"
    QUARANTINE = "quarantine"


class ToolResult(BaseModel):
    """Structured result from a tool invocation."""

    model_config = ConfigDict(frozen=True)

    tool_name: str = Field(min_length=1)
    status: ToolStatus
    output: str = ""
    error_code: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    """Verification outcome tied to evidence shown during generation."""

    model_config = ConfigDict(frozen=True)

    verification_id: str = Field(default_factory=lambda: _new_id("ver"))
    verified_evidence_ids: tuple[str, ...] = Field(default_factory=tuple)
    passed: bool
    outcome: str = "PASS"  # PASS | WARN | FAIL
    reason: str = ""
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    faithfulness: float | None = Field(default=None, ge=0.0, le=1.0)
    answer_relevance: float | None = Field(default=None, ge=0.0, le=1.0)
    citation_correctness: float | None = Field(default=None, ge=0.0, le=1.0)
    citation_completeness: float | None = Field(default=None, ge=0.0, le=1.0)
    abstained: bool = False
    flagged_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TraceEvent(BaseModel):
    """Structured audit event for pipeline tracing."""

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=lambda: _new_id("trc"))
    timestamp: datetime = Field(default_factory=_utc_now)
    node: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    message: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResponse(BaseModel):
    """Canonical agent response with explicit evidence and citation linkage."""

    model_config = ConfigDict(frozen=True)

    answer: str
    mode: str = Field(min_length=1)
    route: str | None = None
    strategy: str | None = None
    evidence: tuple[Evidence, ...] = Field(default_factory=tuple)
    citations: tuple[Citation, ...] = Field(default_factory=tuple)
    verification: VerificationResult | None = None
    trace: tuple[TraceEvent, ...] = Field(default_factory=tuple)
    follow_ups: tuple[str, ...] = Field(default_factory=tuple)
    tenant_id: str | None = None
    error_code: str | None = None
    latency_ms: float | None = None
    response_status: str | None = None  # answered | answered_with_warning | abstained

    @model_validator(mode="after")
    def _citations_reference_evidence(self) -> AgentResponse:
        known = {evidence.evidence_id for evidence in self.evidence}
        for citation in self.citations:
            if citation.evidence_id not in known:
                raise ValueError(
                    f"Citation references unknown evidence_id={citation.evidence_id!r}"
                )
        return self
