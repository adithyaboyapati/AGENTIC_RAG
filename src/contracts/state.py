"""Canonical agent state contract for graph migration."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.contracts.models import (
    Citation,
    Evidence,
    RetrievalPlan,
    RetrievalResult,
    ToolResult,
    TraceEvent,
    VerificationResult,
)
from src.schemas import RBACContext


class CanonicalAgentState(BaseModel):
    """Unified canonical state for the Phase 3 graph."""

    model_config = ConfigDict(frozen=True)

    original_question: str = Field(min_length=1)
    rbac_context: RBACContext = Field(default_factory=RBACContext)
    mode: str = "canonical"

    route: str = ""
    route_reason: str = ""
    strategy: str = "simple"
    strategy_reason: str = ""
    strategy_decision_source: str = "heuristic"

    search_query: str = ""
    retrieval_plan: RetrievalPlan | None = None
    retrieval_results: tuple[RetrievalResult, ...] = Field(default_factory=tuple)
    evidence: tuple[Evidence, ...] = Field(default_factory=tuple)
    generation_evidence_ids: tuple[str, ...] = Field(default_factory=tuple)
    context_text: str = ""

    citations: tuple[Citation, ...] = Field(default_factory=tuple)
    tool_results: tuple[ToolResult, ...] = Field(default_factory=tuple)
    verification: VerificationResult | None = None
    trace: tuple[TraceEvent, ...] = Field(default_factory=tuple)

    answer: str = ""
    follow_ups: tuple[str, ...] = Field(default_factory=tuple)
    error_code: str | None = None
    latency_ms: float | None = None

    retry_count: int = Field(default=0, ge=0)
    current_hop: int = Field(default=0, ge=0)
    abort: bool = False
    abort_reason: str = ""

    llm_call_count: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("original_question")
    @classmethod
    def _strip_question(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("original_question must not be empty")
        return stripped

    @property
    def tenant_id(self) -> str:
        return self.rbac_context.tenant_id

    @property
    def retrieval_result_ids(self) -> frozenset[str]:
        return frozenset(result.result_id for result in self.retrieval_results)

    @property
    def evidence_ids(self) -> frozenset[str]:
        return frozenset(item.evidence_id for item in self.evidence)

    @property
    def question(self) -> str:
        """Alias for original_question — must never differ."""
        return self.original_question
