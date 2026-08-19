"""Prometheus metrics for the Agentic RAG API."""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

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


def metrics_payload() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
