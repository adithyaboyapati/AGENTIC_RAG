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
        return {"status": "ok", "detail": f"{count} documents indexed"}
    except Exception as exc:
        # Full details go to logs; the response only exposes the error class
        # (this endpoint is unauthenticated).
        logger.exception("Chroma health check failed")
        return {"status": "error", "detail": f"Vector store unavailable ({type(exc).__name__})"}


def check_openai_configured() -> dict[str, str]:
    """Verify OpenAI API key is set (does not call the API)."""
    if not settings.openai_api_key:
        return {"status": "error", "detail": "OPENAI_API_KEY not configured"}
    return {"status": "ok", "detail": "API key configured"}


def check_data_directory() -> dict[str, str]:
    """Verify Chroma persist directory exists."""
    path = Path(settings.chroma_persist_dir)
    if not path.exists():
        return {"status": "error", "detail": f"Directory missing: {path}"}
    return {"status": "ok", "detail": str(path)}


def deep_health() -> dict:
    """Aggregate health status for /health/ready."""
    checks = {
        "chroma": check_chroma(),
        "openai": check_openai_configured(),
        "data_dir": check_data_directory(),
    }
    statuses = [c["status"] for c in checks.values()]
    if any(s == "error" for s in statuses):
        overall = "unhealthy"
    elif any(s == "degraded" for s in statuses):
        overall = "degraded"
    else:
        overall = "healthy"
    return {
        "status": overall,
        "service": "agentic-rag",
        "environment": settings.environment,
        "checks": checks,
    }
