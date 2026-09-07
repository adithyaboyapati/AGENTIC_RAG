"""Prometheus metrics for the Agentic RAG API."""

from __future__ import annotations

from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from src.config import settings

REQUESTS = Counter(
    "rag_requests_total",
    "Total /query and /query/stream requests",
    ["mode", "endpoint", "status"],
)
REQUEST_LATENCY = Histogram(
    "rag_request_latency_seconds",
    "Request latency in seconds",
    ["mode", "endpoint"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)
CACHE_EVENTS = Counter(
    "rag_cache_events_total",
    "Answer cache hits and writes",
    ["event"],
)
LLM_FALLBACKS = Counter(
    "rag_llm_fallback_total",
    "Primary LLM → Groq fallback activations",
)
RATE_LIMIT_HITS = Counter(
    "rag_rate_limit_total",
    "Client rate-limit rejections (429)",
)
NODE_GATES = Counter(
    "rag_node_gate_total",
    "Node/tool output gate outcomes (poison containment)",
    ["result"],
)
CAPACITY_REJECTIONS = Counter(
    "rag_capacity_rejections_total",
    "Requests rejected because all concurrency slots were busy (503)",
)
INJECTION_ATTEMPTS = Counter(
    "rag_injection_attempts_total",
    "Total prompt injection and jailbreak attempts detected",
    ["direction", "pattern_type"],
)
# Ingestion pipeline metrics
INGEST_JOBS_TOTAL = Counter(
    "rag_ingest_jobs_total",
    "Total asynchronous document ingestion jobs processed",
    ["status"],
)
INGEST_CHUNKS_TOTAL = Counter(
    "rag_ingest_chunks_total",
    "Total document chunks ingested into vector store",
)
INGEST_DURATION_SECONDS = Histogram(
    "rag_ingest_duration_seconds",
    "Wall-clock duration of document ingestion jobs in seconds",
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0),
)

# Cost is a first-class operational concern here, so it belongs in the scrape
# output — not only in the logs.
TOKENS = Counter(
    "rag_tokens_total",
    "LLM tokens consumed",
    ["provider", "direction"],
)
COST_USD = Counter(
    "rag_cost_usd_total",
    "Estimated LLM spend in USD",
    ["provider"],
)
FEEDBACK = Counter(
    "rag_feedback_total",
    "User thumbs up/down on answers",
    ["mode", "rating"],
)
FEEDBACK_CATEGORIES = Counter(
    "rag_feedback_categories_total",
    "Failure categories attached to negative feedback",
    ["mode", "category"],
)

SHADOW_REQUESTS = Counter(
    "rag_shadow_requests_total",
    "Shadow evaluation requests processed",
    ["execution_mode"],
)
SHADOW_ERRORS = Counter(
    "rag_shadow_errors_total",
    "Shadow evaluation errors",
    ["error_type"],
)
SHADOW_CANONICAL_WINS = Counter(
    "rag_shadow_canonical_wins_total",
    "Shadow comparisons where canonical won",
    ["route", "strategy"],
)
SHADOW_LEGACY_WINS = Counter(
    "rag_shadow_legacy_wins_total",
    "Shadow comparisons where legacy won",
    ["route", "strategy"],
)
SHADOW_INCONCLUSIVE = Counter(
    "rag_shadow_inconclusive_total",
    "Shadow comparisons marked inconclusive",
    ["route", "strategy"],
)
CANONICAL_FALLBACK = Counter(
    "rag_canonical_fallback_total",
    "Canonical executions that used safe failure instead of legacy",
    ["reason"],
)
DEPRECATED_MODES = Counter(
    "rag_deprecated_mode_requests_total",
    "Requests using deprecated legacy mode names",
    ["mode"],
)
CANARY_REQUESTS = Counter(
    "rag_canary_requests_total",
    "User-visible canary traffic assignments",
    ["stage"],
)
CANARY_SUCCESS = Counter(
    "rag_canary_success_total",
    "Canary requests served by canonical without fallback",
    ["stage"],
)
CANARY_FAILURES = Counter(
    "rag_canary_failures_total",
    "Canary canonical execution failures",
    ["stage"],
)
CANARY_FALLBACK = Counter(
    "rag_canary_fallback_total",
    "Canary requests that fell back to legacy",
    ["stage", "fallback_reason"],
)
CANARY_CANONICAL_WINS = Counter(
    "rag_canary_canonical_wins_total",
    "Canary paired comparisons where canonical won",
    ["stage", "route", "strategy"],
)
CANARY_LEGACY_WINS = Counter(
    "rag_canary_legacy_wins_total",
    "Canary paired comparisons where legacy won",
    ["stage", "route", "strategy"],
)
CANARY_EQUIVALENT = Counter(
    "rag_canary_equivalent_total",
    "Canary paired comparisons marked equivalent",
    ["stage", "route", "strategy"],
)
CANARY_INCONCLUSIVE = Counter(
    "rag_canary_inconclusive_total",
    "Canary paired comparisons marked inconclusive",
    ["stage", "route", "strategy"],
)
CANARY_LATENCY_DELTA = Histogram(
    "rag_canary_latency_delta_seconds",
    "Canonical minus legacy latency during canary",
    ["stage", "route", "strategy"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)
CANARY_COST_DELTA = Histogram(
    "rag_canary_cost_delta",
    "Canonical minus legacy estimated cost during canary",
    ["stage", "route", "strategy"],
    buckets=(0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
)
CANARY_TOKEN_DELTA = Histogram(
    "rag_canary_token_delta",
    "Canonical minus legacy token count during canary",
    ["stage", "route", "strategy"],
    buckets=(10, 50, 100, 250, 500, 1000, 2500, 5000, 10000),
)
LEGACY_INVOCATIONS = Counter(
    "rag_legacy_invocations_total",
    "Legacy pipeline invocations after cutover/canary",
    ["reason"],
)
SHADOW_LATENCY_DELTA = Histogram(
    "rag_shadow_latency_delta_seconds",
    "Canonical minus legacy latency in seconds",
    ["route", "strategy"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)
SHADOW_COST_DELTA = Histogram(
    "rag_shadow_cost_delta_usd",
    "Canonical minus legacy estimated cost in USD",
    ["route", "strategy"],
    buckets=(0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
)
SHADOW_TOKEN_DELTA = Histogram(
    "rag_shadow_token_delta",
    "Canonical minus legacy token count",
    ["route", "strategy"],
    buckets=(10, 50, 100, 250, 500, 1000, 2500, 5000, 10000),
)

# Phase 8: continuous evaluation / agentic efficiency
STRATEGY_REQUESTS = Counter(
    "rag_strategy_requests_total",
    "Production requests by canonical strategy",
    ["strategy", "decision_source"],
)
INEFFICIENT_AGENTIC = Counter(
    "rag_inefficient_agentic_total",
    "Detected unnecessary agentic work",
    ["kind"],
)
PRODUCTION_OBSERVATIONS = Counter(
    "rag_production_observations_total",
    "Production observations recorded for continuous eval",
    ["response_status"],
)
REGRESSION_CANDIDATES = Counter(
    "rag_regression_candidates_total",
    "Regression candidates created from production signals",
    ["source_event", "failure_category"],
)


def record_request(mode: str, endpoint: str, status: str, latency_s: float) -> None:
    REQUESTS.labels(mode=mode or "unknown", endpoint=endpoint, status=status).inc()
    REQUEST_LATENCY.labels(mode=mode or "unknown", endpoint=endpoint).observe(max(0.0, latency_s))


def record_cache_hit() -> None:
    CACHE_EVENTS.labels(event="hit").inc()


def record_cache_miss_write() -> None:
    CACHE_EVENTS.labels(event="write").inc()


def record_llm_fallback() -> None:
    LLM_FALLBACKS.inc()


def record_rate_limit_hit() -> None:
    RATE_LIMIT_HITS.inc()


def record_node_gate(result: str) -> None:
    """result: quarantine | abort"""
    NODE_GATES.labels(result=result or "unknown").inc()


def record_capacity_rejection() -> None:
    CAPACITY_REJECTIONS.inc()


def record_injection_attempt(direction: str, pattern_type: str) -> None:
    """Export detected prompt injection or jailbreak attempt."""
    INJECTION_ATTEMPTS.labels(
        direction=direction or "unknown",
        pattern_type=pattern_type or "unknown",
    ).inc()


def record_token_usage(
    provider: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
) -> None:
    """Export per-query token counts and estimated spend."""
    label = provider or "unknown"
    if prompt_tokens > 0:
        TOKENS.labels(provider=label, direction="input").inc(prompt_tokens)
    if completion_tokens > 0:
        TOKENS.labels(provider=label, direction="output").inc(completion_tokens)
    if cost_usd > 0:
        COST_USD.labels(provider=label).inc(cost_usd)


def record_ingest_job(status: str) -> None:
    INGEST_JOBS_TOTAL.labels(status=status or "unknown").inc()


def record_ingest_chunks(count: int) -> None:
    if count > 0:
        INGEST_CHUNKS_TOTAL.inc(count)


def record_ingest_duration(duration_s: float) -> None:
    if duration_s >= 0.0:
        INGEST_DURATION_SECONDS.observe(duration_s)


def record_feedback(mode: str, rating: str, categories: list[str] | None = None) -> None:
    label = mode or "unknown"
    FEEDBACK.labels(mode=label, rating=rating or "unknown").inc()
    for category in categories or []:
        FEEDBACK_CATEGORIES.labels(mode=label, category=category).inc()


def record_shadow_comparison(
    *,
    comparison_status: str,
    route: str,
    strategy: str,
    latency_delta_s: float,
    cost_delta: float,
    token_delta: int,
) -> None:
    route_label = route or "unknown"
    strategy_label = strategy or "unknown"
    if comparison_status == "canonical_better":
        SHADOW_CANONICAL_WINS.labels(route=route_label, strategy=strategy_label).inc()
    elif comparison_status == "legacy_better":
        SHADOW_LEGACY_WINS.labels(route=route_label, strategy=strategy_label).inc()
    elif comparison_status == "inconclusive":
        SHADOW_INCONCLUSIVE.labels(route=route_label, strategy=strategy_label).inc()
    SHADOW_LATENCY_DELTA.labels(route=route_label, strategy=strategy_label).observe(
        max(0.0, latency_delta_s)
    )
    SHADOW_COST_DELTA.labels(route=route_label, strategy=strategy_label).observe(
        max(0.0, cost_delta)
    )
    SHADOW_TOKEN_DELTA.labels(route=route_label, strategy=strategy_label).observe(
        float(token_delta)
    )


def record_shadow_request(execution_mode: str) -> None:
    SHADOW_REQUESTS.labels(execution_mode=execution_mode or "unknown").inc()


def record_shadow_error(error_type: str) -> None:
    SHADOW_ERRORS.labels(error_type=error_type or "unknown").inc()


def record_canonical_fallback(reason: str) -> None:
    CANONICAL_FALLBACK.labels(reason=(reason or "unknown")[:80]).inc()


def record_deprecated_mode(mode: str) -> None:
    DEPRECATED_MODES.labels(mode=(mode or "unknown")[:32]).inc()


def record_canary_request(stage: str) -> None:
    CANARY_REQUESTS.labels(stage=(stage or "0")[:16]).inc()


def record_canary_success(stage: str) -> None:
    CANARY_SUCCESS.labels(stage=(stage or "0")[:16]).inc()


def record_canary_failure(stage: str) -> None:
    CANARY_FAILURES.labels(stage=(stage or "0")[:16]).inc()


def record_canary_fallback(reason: str, stage: str) -> None:
    CANARY_FALLBACK.labels(
        stage=(stage or "0")[:16],
        fallback_reason=(reason or "unknown")[:80],
    ).inc()
    if settings.legacy_runtime_enabled:
        record_legacy_invocation(reason or "canary_fallback")


def record_canary_comparison(
    *,
    comparison_status: str,
    stage: str,
    route: str,
    strategy: str,
    latency_delta_s: float,
    cost_delta: float,
    token_delta: int,
) -> None:
    stage_label = (stage or "0")[:16]
    route_label = (route or "unknown")[:32]
    strategy_label = (strategy or "unknown")[:32]
    if comparison_status == "canonical_better":
        CANARY_CANONICAL_WINS.labels(
            stage=stage_label, route=route_label, strategy=strategy_label
        ).inc()
    elif comparison_status == "legacy_better":
        CANARY_LEGACY_WINS.labels(
            stage=stage_label, route=route_label, strategy=strategy_label
        ).inc()
    elif comparison_status == "equivalent":
        CANARY_EQUIVALENT.labels(
            stage=stage_label, route=route_label, strategy=strategy_label
        ).inc()
    elif comparison_status == "inconclusive":
        CANARY_INCONCLUSIVE.labels(
            stage=stage_label, route=route_label, strategy=strategy_label
        ).inc()
    CANARY_LATENCY_DELTA.labels(
        stage=stage_label, route=route_label, strategy=strategy_label
    ).observe(max(0.0, latency_delta_s))
    CANARY_COST_DELTA.labels(
        stage=stage_label, route=route_label, strategy=strategy_label
    ).observe(max(0.0, cost_delta))
    CANARY_TOKEN_DELTA.labels(
        stage=stage_label, route=route_label, strategy=strategy_label
    ).observe(float(token_delta))


def record_legacy_invocation(reason: str) -> None:
    LEGACY_INVOCATIONS.labels(reason=(reason or "unknown")[:80]).inc()


def record_production_observation(obs: Any) -> None:
    PRODUCTION_OBSERVATIONS.labels(
        response_status=(getattr(obs, "response_status", None) or "unknown")[:32]
    ).inc()
    STRATEGY_REQUESTS.labels(
        strategy=(getattr(obs, "strategy", None) or "unknown")[:32],
        decision_source=(getattr(obs, "strategy_decision_source", None) or "unknown")[:16],
    ).inc()
    if getattr(obs, "strategy_llm_redundant", False):
        INEFFICIENT_AGENTIC.labels(kind="strategy_llm_redundant").inc()
    if getattr(obs, "ineffective_retry", False):
        INEFFICIENT_AGENTIC.labels(kind="ineffective_retry").inc()
    if getattr(obs, "unnecessary_multihop", False):
        INEFFICIENT_AGENTIC.labels(kind="unnecessary_multihop").inc()


def record_regression_candidate(source_event: str, failure_category: str) -> None:
    REGRESSION_CANDIDATES.labels(
        source_event=(source_event or "unknown")[:32],
        failure_category=(failure_category or "unknown")[:32],
    ).inc()


def metrics_payload() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
