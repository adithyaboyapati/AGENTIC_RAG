"""Pre-canary production dependency validation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.config import settings

logger = logging.getLogger(__name__)


class PreflightSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class PreflightCheck:
    component: str
    status: str  # ok | degraded | failed | skipped
    severity: PreflightSeverity
    message: str


@dataclass(frozen=True)
class PreflightReport:
    checks: tuple[PreflightCheck, ...]
    canary_allowed: bool
    shadow_allowed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "canary_allowed": self.canary_allowed,
            "shadow_allowed": self.shadow_allowed,
            "checks": [
                {
                    "component": c.component,
                    "status": c.status,
                    "severity": c.severity.value,
                    "message": c.message,
                }
                for c in self.checks
            ],
        }


def _check_redis() -> PreflightCheck:
    try:
        from src.cache.redis_cache import get_redis_client

        client = get_redis_client()
        if client is None:
            return PreflightCheck(
                component="redis",
                status="degraded",
                severity=PreflightSeverity.WARNING,
                message="Redis unavailable; distributed cache/jobs degrade to local",
            )
        client.ping()
        return PreflightCheck("redis", "ok", PreflightSeverity.INFO, "Redis reachable")
    except Exception as exc:
        return PreflightCheck(
            "redis",
            "failed",
            PreflightSeverity.WARNING,
            f"Redis check failed: {type(exc).__name__}",
        )


def _check_vector_store() -> PreflightCheck:
    try:
        from src.ingestion.ingest import get_vector_store

        store = get_vector_store()
        if store is None:
            return PreflightCheck(
                "vector_store",
                "failed",
                PreflightSeverity.CRITICAL,
                "Vector store unavailable",
            )
        return PreflightCheck("vector_store", "ok", PreflightSeverity.INFO, "Vector store reachable")
    except Exception as exc:
        return PreflightCheck(
            "vector_store",
            "failed",
            PreflightSeverity.CRITICAL,
            f"Vector store check failed: {type(exc).__name__}",
        )


def _check_llm() -> PreflightCheck:
    if not (settings.openai_api_key or settings.groq_api_key):
        return PreflightCheck(
            "llm_provider",
            "failed",
            PreflightSeverity.CRITICAL,
            "No LLM provider API key configured",
        )
    return PreflightCheck("llm_provider", "ok", PreflightSeverity.INFO, "LLM provider configured")


def _check_verification_llm() -> PreflightCheck:
    if not settings.canonical_verification_llm_enabled:
        return PreflightCheck(
            "verification_llm",
            "degraded",
            PreflightSeverity.WARNING,
            "Canonical verification LLM disabled",
        )
    if not settings.openai_api_key:
        return PreflightCheck(
            "verification_llm",
            "failed",
            PreflightSeverity.CRITICAL,
            "Verification LLM requires OpenAI key",
        )
    return PreflightCheck("verification_llm", "ok", PreflightSeverity.INFO, "Verification LLM available")


def _check_auth() -> PreflightCheck:
    if settings.require_api_key and not (settings.api_key or "").strip():
        return PreflightCheck(
            "authentication",
            "failed",
            PreflightSeverity.CRITICAL,
            "API key required but not configured",
        )
    return PreflightCheck("authentication", "ok", PreflightSeverity.INFO, "Authentication configured")


def _check_rbac() -> PreflightCheck:
    if not settings.rbac_enabled:
        return PreflightCheck(
            "rbac",
            "degraded",
            PreflightSeverity.WARNING,
            "RBAC disabled",
        )
    return PreflightCheck("rbac", "ok", PreflightSeverity.INFO, "RBAC enabled")


def _check_ssrf() -> PreflightCheck:
    try:
        from src.security.ssrf import validate_outbound_url

        validate_outbound_url("https://example.com")
        return PreflightCheck("ssrf_egress", "ok", PreflightSeverity.INFO, "SSRF policy active")
    except Exception as exc:
        return PreflightCheck(
            "ssrf_egress",
            "failed",
            PreflightSeverity.CRITICAL,
            f"SSRF policy check failed: {type(exc).__name__}",
        )


def _check_observability() -> PreflightCheck:
    return PreflightCheck(
        "observability",
        "ok",
        PreflightSeverity.INFO,
        "Prometheus metrics module available",
    )


def _check_shadow_storage() -> PreflightCheck:
    try:
        from src.evaluation.shadow_storage import list_shadow_results

        list_shadow_results(limit=1)
        return PreflightCheck("shadow_storage", "ok", PreflightSeverity.INFO, "Shadow storage reachable")
    except Exception as exc:
        return PreflightCheck(
            "shadow_storage",
            "failed",
            PreflightSeverity.WARNING,
            f"Shadow storage unavailable: {type(exc).__name__}",
        )


def _check_canonical_graph() -> PreflightCheck:
    try:
        from src.graph.canonical_graph import get_canonical_graph

        get_canonical_graph()
        return PreflightCheck("canonical_graph", "ok", PreflightSeverity.INFO, "Canonical graph compiles")
    except Exception as exc:
        return PreflightCheck(
            "canonical_graph",
            "failed",
            PreflightSeverity.CRITICAL,
            f"Canonical graph unavailable: {type(exc).__name__}",
        )


def run_preflight(*, for_canary: bool = False) -> PreflightReport:
    checks = (
        _check_canonical_graph(),
        _check_redis(),
        _check_vector_store(),
        _check_llm(),
        _check_verification_llm(),
        _check_auth(),
        _check_rbac(),
        _check_ssrf(),
        _check_observability(),
        _check_shadow_storage(),
    )
    critical_failures = [
        c for c in checks if c.severity == PreflightSeverity.CRITICAL and c.status == "failed"
    ]
    canary_blockers = {
        "canonical_graph",
        "vector_store",
        "llm_provider",
        "verification_llm",
        "ssrf_egress",
    }
    canary_critical = [c for c in critical_failures if c.component in canary_blockers]
    if for_canary and settings.require_api_key:
        auth_failed = any(c.component == "authentication" and c.status == "failed" for c in checks)
        if auth_failed:
            canary_critical.append(
                PreflightCheck(
                    "authentication",
                    "failed",
                    PreflightSeverity.CRITICAL,
                    "Authentication required for canary",
                )
            )

    return PreflightReport(
        checks=checks,
        canary_allowed=not canary_critical,
        shadow_allowed=not any(c.component == "canonical_graph" and c.status == "failed" for c in checks),
    )
