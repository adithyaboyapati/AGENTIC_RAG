"""Shadow evaluation contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExecutionMode(str, Enum):
    REPLAY = "replay"
    SHADOW = "shadow"
    CANARY = "canary"


class ComparisonStatus(str, Enum):
    CANONICAL_BETTER = "canonical_better"
    LEGACY_BETTER = "legacy_better"
    EQUIVALENT = "equivalent"
    INCONCLUSIVE = "inconclusive"
    ERROR = "error"


class DisagreementClass(str, Enum):
    LEGACY_CORRECT_CANONICAL_WRONG = "legacy_correct_canonical_wrong"
    CANONICAL_CORRECT_LEGACY_WRONG = "canonical_correct_legacy_wrong"
    BOTH_CORRECT = "both_correct"
    BOTH_WRONG = "both_wrong"
    BOTH_ABSTAINED = "both_abstained"
    CANONICAL_ABSTAINED_LEGACY_ANSWERED = "canonical_abstained_legacy_answered"
    LEGACY_ABSTAINED_CANONICAL_ANSWERED = "legacy_abstained_canonical_answered"
    CITATION_DISAGREEMENT = "citation_disagreement"
    RETRIEVAL_DISAGREEMENT = "retrieval_disagreement"
    NONE = "none"
    INCONCLUSIVE = "inconclusive"


class PipelineMetrics(BaseModel):
    """Structured metrics for one pipeline execution."""

    model_config = ConfigDict(frozen=True)

    pipeline: str
    mode: str | None = None
    route: str | None = None
    strategy: str | None = None
    strategy_source: str | None = None
    response_status: str | None = None

    faithfulness: float | None = None
    answer_relevance: float | None = None
    correctness: float | None = None
    citation_correctness: float | None = None
    citation_completeness: float | None = None

    recall_at_k: float | None = None
    evidence_count: int = 0
    useful_evidence_count: int = 0
    retrieval_failures: int = 0

    retry_count: int = 0
    hop_count: int = 0
    llm_call_count: int | None = None
    verification_count: int = 0
    web_search_count: int = 0

    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None

    error_code: str | None = None
    abstained: bool = False
    answer_length: int = 0
    answer_hash: str | None = None


class ShadowResult(BaseModel):
    """Paired legacy + canonical evaluation record."""

    model_config = ConfigDict(frozen=True)

    request_id: str
    tenant_id: str
    input_fingerprint: str
    execution_mode: ExecutionMode

    legacy_mode: str
    canonical_strategy: str | None = None

    legacy_metrics: PipelineMetrics
    canonical_metrics: PipelineMetrics

    legacy_response_summary: dict[str, Any] = Field(default_factory=dict)
    canonical_response_summary: dict[str, Any] = Field(default_factory=dict)

    latency_delta_ms: float | None = None
    cost_delta_usd: float | None = None
    token_delta: int | None = None

    comparison_status: ComparisonStatus = ComparisonStatus.INCONCLUSIVE
    disagreement_class: DisagreementClass = DisagreementClass.INCONCLUSIVE
    winner: str | None = None

    quality_deltas: dict[str, float | None] = Field(default_factory=dict)
    sampling: dict[str, Any] = Field(default_factory=dict)
    eval_config_hash: str | None = None
    errors: tuple[str, ...] = Field(default_factory=tuple)
    fallback_reason: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.utcnow())
