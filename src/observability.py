"""
LangSmith observability and tracing setup.

Initializes LangSmith tracing when enabled in configuration.
Must run before any LangChain/LangGraph chain is imported.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager

from src.config import settings

logger = logging.getLogger(__name__)

_initialized = False


def _clear_langsmith_env_cache() -> None:
    """LangSmith caches env lookups — clear after we set variables."""
    try:
        from langsmith.utils import get_env_var

        get_env_var.cache_clear()
    except Exception:
        pass


def init_langsmith_tracing() -> bool:
    """
    Initialize LangSmith tracing if enabled.

    Sets both LANGSMITH_* and LANGCHAIN_* env vars (LangSmith checks both).
    """
    global _initialized

    if not settings.langsmith_tracing:
        logger.debug("LangSmith tracing disabled (LANGSMITH_TRACING=false)")
        return False

    if not settings.langsmith_api_key:
        logger.warning("LangSmith tracing enabled but LANGSMITH_API_KEY is missing")
        return False

    project = settings.langsmith_project.strip('"').strip("'")
    endpoint = settings.langsmith_endpoint
    api_key = settings.langsmith_api_key

    # LangSmith SDK checks LANGSMITH_* first, then LANGCHAIN_* fallbacks
    tracing_vars = {
        "LANGSMITH_TRACING": "true",
        "LANGSMITH_TRACING_V2": "true",
        "LANGSMITH_API_KEY": api_key,
        "LANGSMITH_ENDPOINT": endpoint,
        "LANGSMITH_PROJECT": project,
        "LANGCHAIN_TRACING_V2": "true",
        "LANGCHAIN_API_KEY": api_key,
        "LANGCHAIN_ENDPOINT": endpoint,
        "LANGCHAIN_PROJECT": project,
    }
    os.environ.update(tracing_vars)
    _clear_langsmith_env_cache()

    _initialized = True
    logger.info("LangSmith tracing enabled | project=%s", project)
    return True


def is_tracing_enabled() -> bool:
    """Check if LangSmith tracing is active."""
    if not settings.langsmith_tracing or not settings.langsmith_api_key:
        return False
    try:
        from langsmith.utils import tracing_is_enabled

        return bool(tracing_is_enabled())
    except Exception:
        return _initialized


def get_tracing_status() -> dict[str, str]:
    """Return tracing status for UI/diagnostics."""
    project = settings.langsmith_project.strip('"').strip("'")
    return {
        "configured": str(settings.langsmith_tracing and bool(settings.langsmith_api_key)),
        "active": str(is_tracing_enabled()),
        "project": project,
        "endpoint": settings.langsmith_endpoint,
    }


@contextmanager
def traced_execution(run_name: str):
    """Context manager for custom trace run names."""
    if is_tracing_enabled():
        os.environ["LANGCHAIN_RUN_NAME"] = run_name
    try:
        yield
    finally:
        if is_tracing_enabled():
            os.environ.pop("LANGCHAIN_RUN_NAME", None)


# Initialize on first import of this module
init_langsmith_tracing()
