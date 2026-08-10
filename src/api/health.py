"""Deep health checks for production readiness probes."""

from __future__ import annotations

import logging
from pathlib import Path

from src.config import settings

logger = logging.getLogger(__name__)


def check_chroma() -> dict[str, str]:
    """Verify ChromaDB is reachable and collection has documents."""
    try:
        from src.ingestion.ingest import get_vector_store

        store = get_vector_store()
        count = store._collection.count()  # noqa: SLF001 — health probe only
        if count == 0:
            return {"status": "degraded", "detail": "Vector store is empty — run ingestion"}
        mode = (settings.chroma_mode or "persistent").strip().lower()
        return {
            "status": "ok",
            "detail": f"{count} documents indexed (mode={mode})",
        }
    except Exception as exc:
        logger.exception("Chroma health check failed")
        return {"status": "error", "detail": f"Vector store unavailable ({type(exc).__name__})"}


def check_openai_configured() -> dict[str, str]:
    """Verify OpenAI API key is set (does not call the API)."""
    if not settings.openai_api_key:
        return {"status": "error", "detail": "OPENAI_API_KEY not configured"}
    return {"status": "ok", "detail": "API key configured"}


def check_data_directory() -> dict[str, str]:
    """Verify Chroma persist directory exists (persistent mode only)."""
    mode = (settings.chroma_mode or "persistent").strip().lower()
    if mode == "http":
        return {
            "status": "ok",
            "detail": f"http://{settings.chroma_host}:{settings.chroma_port}",
        }
    path = Path(settings.chroma_persist_dir)
    if not path.exists():
        return {"status": "error", "detail": f"Directory missing: {path}"}
    return {"status": "ok", "detail": str(path)}


def check_redis() -> dict[str, str]:
    """Ping Redis when cache or shared rate limits may use it."""
    needs_redis = settings.cache_enabled or (
        (settings.rate_limit_backend or "auto").strip().lower() != "memory"
    )
    if not needs_redis:
        return {"status": "skipped", "detail": "Redis not required"}
    if not (settings.redis_url or "").strip():
        return {"status": "degraded", "detail": "REDIS_URL empty"}
    try:
        from src.cache.redis_cache import allow_redis_reconnect, get_redis_client

        allow_redis_reconnect()
        client = get_redis_client()
        if client is None:
            return {"status": "degraded", "detail": "Redis unreachable"}
        client.ping()
        return {"status": "ok", "detail": "pong"}
    except Exception as exc:
        logger.warning("Redis health check failed: %s", type(exc).__name__)
        return {"status": "degraded", "detail": f"Redis error ({type(exc).__name__})"}


def check_groq_configured() -> dict[str, str]:
    if not settings.llm_fallback_enabled:
        return {"status": "skipped", "detail": "LLM fallback disabled"}
    if not settings.groq_api_key:
        return {"status": "skipped", "detail": "GROQ_API_KEY not set"}
    return {"status": "ok", "detail": f"fallback model={settings.groq_model}"}


def check_supabase_configured() -> dict[str, str]:
    if not settings.memory_enabled:
        return {"status": "skipped", "detail": "Memory disabled"}
    if not settings.supabase_url or not settings.supabase_key:
        return {"status": "skipped", "detail": "Supabase not configured"}
    return {"status": "ok", "detail": "Supabase credentials present"}


def check_nvidia_configured() -> dict[str, str]:
    if not settings.rerank_enabled:
        return {"status": "skipped", "detail": "Rerank disabled"}
    provider = (settings.rerank_provider or "").strip().lower()
    if provider != "nvidia":
        return {"status": "skipped", "detail": f"provider={provider or 'none'}"}
    if not (settings.nvidia_api_key or "").strip():
        return {"status": "degraded", "detail": "NVIDIA_API_KEY missing for nvidia rerank"}
    return {"status": "ok", "detail": "NVIDIA API key configured"}


def deep_health() -> dict:
    """Aggregate health status for /health/ready."""
    checks = {
        "chroma": check_chroma(),
        "openai": check_openai_configured(),
        "data_dir": check_data_directory(),
        "redis": check_redis(),
        "groq": check_groq_configured(),
        "supabase": check_supabase_configured(),
        "nvidia": check_nvidia_configured(),
    }
    # Required for healthy: chroma + openai (+ data_dir in persistent mode)
    required = ["chroma", "openai", "data_dir"]
    required_statuses = [checks[k]["status"] for k in required]
    optional_statuses = [checks[k]["status"] for k in checks if k not in required]

    if any(s == "error" for s in required_statuses):
        overall = "unhealthy"
    elif any(s == "degraded" for s in required_statuses) or any(
        s == "degraded" for s in optional_statuses
    ):
        overall = "degraded"
    else:
        overall = "healthy"
    return {
        "status": overall,
        "service": "agentic-rag",
        "environment": settings.environment,
        "checks": checks,
    }
