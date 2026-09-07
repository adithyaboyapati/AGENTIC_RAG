"""Deterministic shadow/canary sampling."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum

from src.config import settings
from src.evaluation.canary_rollout import effective_canary_percent, is_canary_active
from src.evaluation.shadow_fingerprint import ShadowRequestContext, compute_input_fingerprint


class SamplingDecision(str, Enum):
    SKIP = "skip"
    SHADOW = "shadow"
    CANARY = "canary"


@dataclass(frozen=True)
class SamplingOutcome:
    shadow_enabled: bool
    sampling_rate: float
    sampling_decision: SamplingDecision
    canary_enabled: bool
    canary_percent: float
    bucket: int


def _bucket(input_fingerprint: str, salt: str) -> int:
    digest = hashlib.sha256(f"{salt}:{input_fingerprint}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 10_000


def evaluate_sampling(
    context: ShadowRequestContext,
    *,
    input_fingerprint: str | None = None,
) -> SamplingOutcome:
    """Deterministic per-request sampling; retries with same fingerprint stay stable."""
    fp = input_fingerprint or compute_input_fingerprint(context)
    shadow_rate = float(getattr(settings, "shadow_sampling_rate", 0.0) or 0.0)
    canary_percent = effective_canary_percent() if is_canary_active() else 0.0
    shadow_enabled = bool(getattr(settings, "shadow_enabled", False))

    bucket = _bucket(fp, "shadow-canary-v1")
    threshold_shadow = int(max(0.0, min(1.0, shadow_rate)) * 10_000)
    threshold_canary = int(max(0.0, min(1.0, canary_percent / 100.0)) * 10_000)

    decision = SamplingDecision.SKIP
    if is_canary_active() and canary_percent > 0 and bucket < threshold_canary:
        decision = SamplingDecision.CANARY
    elif shadow_enabled and shadow_rate > 0 and bucket < threshold_shadow:
        decision = SamplingDecision.SHADOW

    return SamplingOutcome(
        shadow_enabled=shadow_enabled,
        sampling_rate=shadow_rate,
        sampling_decision=decision,
        canary_enabled=is_canary_active(),
        canary_percent=canary_percent,
        bucket=bucket,
    )
