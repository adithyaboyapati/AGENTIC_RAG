"""Canonical workflow observability: metrics, timing, and OpenTelemetry."""

from src.canonical_observability.canonical_metrics import (
    record_node_latency,
    record_stage_latency,
    record_verification_outcome,
)
from src.canonical_observability.canonical_timing import timed_node, wrap_canonical_node
from src.canonical_observability.canonical_tracing import canonical_span, start_request_trace

__all__ = [
    "canonical_span",
    "record_node_latency",
    "record_stage_latency",
    "record_verification_outcome",
    "start_request_trace",
    "timed_node",
    "wrap_canonical_node",
]
