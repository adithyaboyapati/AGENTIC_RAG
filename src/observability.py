"""
LangSmith observability and tracing setup.

Initializes LangSmith tracing when enabled in configuration.
Must run before any LangChain/LangGraph chain is imported.

Env vars alone only auto-trace LangChain LLM/runnable calls. Custom retrieval,
graph nodes, and follow-ups would otherwise appear as disconnected ChatOpenAI
runs (question + context + answer). Parent spans below nest the full request.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from contextlib import contextmanager
from functools import wraps
from typing import Any

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
        "LANGCHAIN_CALLBACKS_BACKGROUND": "true",
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


def graph_tracing_config(
    run_name: str,
    metadata: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """RunnableConfig so LangGraph.stream nests under a named run."""
    config: dict[str, Any] = {
        "run_name": run_name,
        "tags": ["agentic-rag", run_name],
        "metadata": dict(metadata or {}),
    }
    config.update(extra)
    return config


def safe_graph_io(state: Any) -> dict[str, Any]:
    """Compact, JSON-safe snapshot of graph state for LangSmith (avoid full docs)."""
    if not isinstance(state, dict):
        return {"type": type(state).__name__}
    out: dict[str, Any] = {}
    if "question" in state:
        out["question"] = state.get("question")
    if "answer" in state:
        out["answer"] = str(state.get("answer") or "")[:2000]
    if "steps" in state:
        steps = state.get("steps") or []
        out["steps"] = list(steps)[-20:] if isinstance(steps, list) else steps
    if "route" in state:
        out["route"] = state.get("route")
    canonical = state.get("canonical")
    if isinstance(canonical, dict):
        out["question"] = canonical.get("original_question") or canonical.get("search_query")
        out["mode"] = canonical.get("mode")
        out["route"] = canonical.get("route")
        out["strategy"] = canonical.get("strategy")
        out["answer"] = str(canonical.get("answer") or "")[:2000]
        out["grade_summary"] = canonical.get("grade_summary")
    return out


def record_response_outputs(run: Any, result: Any, *, cached: bool = False) -> None:
    """Attach compact AgentResponse fields to the parent LangSmith run."""
    if run is None or result is None:
        return
    try:
        run.add_outputs(
            {
                "answer": str(getattr(result, "answer", "") or "")[:4000],
                "route": getattr(result, "route", None),
                "route_reason": getattr(result, "route_reason", None),
                "grade_summary": getattr(result, "grade_summary", None),
                "sources": list(getattr(result, "sources", None) or [])[:20],
                "follow_ups": list(getattr(result, "follow_ups", None) or []),
                "steps": list(getattr(result, "steps", None) or [])[:40],
                "cached": cached,
                "error_code": getattr(result, "error_code", None),
                "verification_status": getattr(result, "verification_status", None),
            }
        )
    except Exception:
        logger.debug("LangSmith output attach skipped", exc_info=True)


@contextmanager
def agent_request_trace(
    *,
    question: str,
    mode: str,
    name: str | None = None,
    metadata: dict[str, Any] | None = None,
):
    """Parent LangSmith span covering query arrival through follow-ups."""
    if not is_tracing_enabled():
        yield None
        return
    try:
        from langsmith import trace
    except Exception:
        yield None
        return

    extra = dict(metadata or {})
    extra.setdefault("mode", mode)
    try:
        from src.logging_config import get_request_id

        extra.setdefault("request_id", get_request_id())
    except Exception:
        pass

    with trace(
        name=name or f"agent_request:{mode}",
        run_type="chain",
        inputs={"question": question, "mode": mode},
        tags=["agentic-rag", "agent_request", mode],
        metadata=extra,
    ) as run:
        yield run


@contextmanager
def traced_execution(run_name: str):
    """Context manager for a named LangSmith span around a block of work."""
    if not is_tracing_enabled():
        yield
        return
    try:
        from langsmith import trace
    except Exception:
        yield
        return
    with trace(name=run_name, run_type="chain"):
        yield


def optional_traceable(
    name: str,
    run_type: str = "chain",
    *,
    process_inputs: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    process_outputs: Callable[..., dict[str, Any]] | None = None,
):
    """@traceable that is a no-op when LangSmith is disabled (tests, local)."""

    def decorator(fn: Callable):
        try:
            from langsmith import traceable

            traced = traceable(
                name=name,
                run_type=run_type,
                process_inputs=process_inputs,
                process_outputs=process_outputs,
            )(fn)
        except Exception:
            traced = fn

        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            if not is_tracing_enabled():
                return fn(*args, **kwargs)
            return traced(*args, **kwargs)

        return wrapper

    return decorator


# Initialize on first import of this module
init_langsmith_tracing()
