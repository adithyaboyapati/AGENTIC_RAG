"""Prometheus metrics for the canonical graph workflow."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

CANONICAL_NODE_LATENCY = Histogram(
    "rag_canonical_node_latency_seconds",
    "Canonical graph node latency in seconds",
    ["node"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

CANONICAL_STAGE_LATENCY = Histogram(
    "rag_canonical_stage_latency_seconds",
    "Canonical pipeline stage latency in seconds",
    ["stage"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

CANONICAL_VERIFICATION = Counter(
    "rag_canonical_verification_total",
    "Canonical verification outcomes",
    ["outcome"],
)


def record_node_latency(node: str, duration_s: float) -> None:
    CANONICAL_NODE_LATENCY.labels(node=node or "unknown").observe(max(0.0, duration_s))


def record_stage_latency(stage: str, duration_s: float) -> None:
    CANONICAL_STAGE_LATENCY.labels(stage=stage or "unknown").observe(max(0.0, duration_s))


def record_verification_outcome(outcome: str) -> None:
    CANONICAL_VERIFICATION.labels(outcome=outcome or "unknown").inc()
