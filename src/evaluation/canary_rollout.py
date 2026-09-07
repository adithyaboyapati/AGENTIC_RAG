"""Runtime canary rollout control, stages, and emergency kill switch."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum

from src.config import settings

_lock = threading.Lock()
_canary_killed = False
_stage_started_at: float | None = None
_current_stage: str | None = None

CANARY_STAGES = ("0", "1", "5", "25", "50", "100")
STAGE_TO_PERCENT = {
    "0": 0.0,
    "1": 1.0,
    "5": 5.0,
    "25": 25.0,
    "50": 50.0,
    "100": 100.0,
}


class RolloutMode(str, Enum):
    LEGACY_ONLY = "legacy_only"
    SHADOW = "shadow"
    CANARY = "canary"
    CANONICAL_PRIMARY = "canonical_primary"


@dataclass(frozen=True)
class RolloutState:
    mode: RolloutMode
    canary_enabled: bool
    canary_percent: float
    canary_stage: str
    shadow_enabled: bool
    shadow_sampling_rate: float
    kill_switch_active: bool
    canonical_primary: bool
    legacy_fallback_enabled: bool
    stage_started_at: float | None
    legacy_traffic_percent: float
    canonical_traffic_percent: float
    shadow_traffic_percent: float


def kill_canary() -> None:
    """Emergency kill switch — stops new canary assignments immediately."""
    global _canary_killed
    with _lock:
        _canary_killed = True


def reset_canary_kill_switch() -> None:
    """Test helper / operator reset after incident."""
    global _canary_killed
    with _lock:
        _canary_killed = False


def is_canary_killed() -> bool:
    with _lock:
        return _canary_killed


def is_canary_active() -> bool:
    if is_canary_killed():
        return False
    if not settings.canary_enabled:
        return False
    return effective_canary_percent() > 0.0


def effective_canary_percent() -> float:
    stage = (getattr(settings, "canary_stage", "0") or "0").strip()
    if stage in STAGE_TO_PERCENT:
        configured = STAGE_TO_PERCENT[stage]
    else:
        configured = float(getattr(settings, "canary_percent", 0.0) or 0.0)
    if configured <= 0:
        return 0.0
    return configured


def note_stage_entry(stage: str) -> None:
    global _stage_started_at, _current_stage
    with _lock:
        _current_stage = stage
        _stage_started_at = time.time()


def get_rollout_state() -> RolloutState:
    canary_pct = effective_canary_percent() if is_canary_active() else 0.0
    shadow_rate = float(settings.shadow_sampling_rate or 0.0) if settings.shadow_enabled else 0.0
    canonical_primary = bool(getattr(settings, "canonical_primary", False))

    if canonical_primary and canary_pct >= 100.0:
        mode = RolloutMode.CANONICAL_PRIMARY
        legacy_pct = 0.0
        canonical_pct = 100.0
    elif canary_pct > 0:
        mode = RolloutMode.CANARY
        legacy_pct = max(0.0, 100.0 - canary_pct)
        canonical_pct = canary_pct
    elif settings.shadow_enabled and shadow_rate > 0:
        mode = RolloutMode.SHADOW
        legacy_pct = 100.0
        canonical_pct = 0.0
    else:
        mode = RolloutMode.LEGACY_ONLY
        legacy_pct = 100.0
        canonical_pct = 0.0

    shadow_pct = shadow_rate * 100.0 if settings.shadow_enabled else 0.0

    return RolloutState(
        mode=mode,
        canary_enabled=settings.canary_enabled and not is_canary_killed(),
        canary_percent=canary_pct,
        canary_stage=(getattr(settings, "canary_stage", "0") or "0"),
        shadow_enabled=settings.shadow_enabled,
        shadow_sampling_rate=shadow_rate,
        kill_switch_active=is_canary_killed() or not settings.canary_enabled,
        canonical_primary=canonical_primary,
        legacy_fallback_enabled=bool(getattr(settings, "legacy_fallback_enabled", True)),
        stage_started_at=_stage_started_at,
        legacy_traffic_percent=legacy_pct,
        canonical_traffic_percent=canonical_pct,
        shadow_traffic_percent=shadow_pct,
    )


def stage_hold_satisfied() -> tuple[bool, str]:
    """Check minimum observation window for current stage."""
    min_samples = max(1, int(getattr(settings, "canary_minimum_samples", 30)))
    min_window = max(0, int(getattr(settings, "canary_minimum_observation_window_seconds", 3600)))
    from src.evaluation.shadow_storage import list_shadow_results

    rows = list_shadow_results(limit=10_000)
    canary_rows = [r for r in rows if r.get("execution_mode") == "canary"]
    if len(canary_rows) < min_samples:
        return False, f"insufficient_samples:{len(canary_rows)}<{min_samples}"
    if _stage_started_at is None:
        return True, "no_stage_timer"
    elapsed = time.time() - _stage_started_at
    if elapsed < min_window:
        return False, f"observation_window:{elapsed:.0f}s<{min_window}s"
    return True, "hold_satisfied"
