"""Deprecated public mode mapping to canonical strategies."""

from __future__ import annotations

import logging

from src.config import settings

logger = logging.getLogger(__name__)

DEPRECATED_LEGACY_MODES = frozenset(
    {
        "baseline",
        "router",
        "crag",
        "decompose",
        "multi_hop",
        "tools",
        "agentic",
        "consensus",
    }
)

PUBLIC_MODES = frozenset({"canonical", *DEPRECATED_LEGACY_MODES})

MODE_TO_CANONICAL_STRATEGY: dict[str, str | None] = {
    "baseline": "simple",
    "router": None,
    "crag": None,
    "decompose": "decompose",
    "multi_hop": "multi_hop",
    "tools": None,
    "agentic": None,
    "consensus": None,
    "canonical": None,
    "canonical-simple": "simple",
    "canonical-decompose": "decompose",
    "canonical-multi-hop": "multi_hop",
}


def normalize_mode(mode: str) -> str:
    return (mode or "agentic").strip().lower()


def is_deprecated_mode(mode: str) -> bool:
    return normalize_mode(mode) in DEPRECATED_LEGACY_MODES


def resolve_canonical_strategy(mode: str) -> str | None:
    """Map a public mode string to a canonical force_strategy value."""
    key = normalize_mode(mode)
    if key not in PUBLIC_MODES and not key.startswith("canonical"):
        raise ValueError(f"Unknown mode: {mode}")
    if key == "consensus" and not settings.consensus_agent_enabled:
        logger.warning("Deprecated consensus mode requested — mapping to canonical auto")
    return MODE_TO_CANONICAL_STRATEGY.get(key)


def record_deprecated_mode_usage(mode: str) -> None:
    if not is_deprecated_mode(mode):
        return
    try:
        from src.api.metrics import record_deprecated_mode

        record_deprecated_mode(normalize_mode(mode))
    except Exception:
        logger.debug("Deprecated mode metric export skipped", exc_info=True)
