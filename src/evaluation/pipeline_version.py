"""Pipeline version identifiers for cache and traffic separation."""

from __future__ import annotations

PIPELINE_LEGACY = "legacy"
PIPELINE_CANONICAL_V1 = "canonical-v1"

SUPPORTED_PIPELINES = frozenset({PIPELINE_LEGACY, PIPELINE_CANONICAL_V1})


def active_pipeline_version() -> str:
    """Return the cache namespace version for the current execution context."""
    from src.config import settings
    from src.evaluation.shadow_context import is_canary_execution, is_shadow_execution

    if is_canary_execution() or settings.canonical_primary:
        return PIPELINE_CANONICAL_V1
    if is_shadow_execution():
        return PIPELINE_LEGACY
    return PIPELINE_CANONICAL_V1 if settings.canonical_primary else PIPELINE_LEGACY


def cache_pipeline_version(*, force: str | None = None) -> str:
    if force is not None:
        return force
    return active_pipeline_version()
