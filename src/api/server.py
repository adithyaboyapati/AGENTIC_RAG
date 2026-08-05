"""
Phase 8: Production API — FastAPI server with auth, CORS, and health checks.

Run:
    uvicorn src.api.server:app --host 0.0.0.0 --port 8000

Authenticated query:
    curl -X POST http://localhost:8000/query \
      -H "Content-Type: application/json" \
      -H "X-API-Key: your-api-key" \
      -d '{"question": "What is Self-RAG?", "mode": "agentic"}'
"""

from __future__ import annotations

import src.bootstrap  # noqa: F401 — enable LangSmith before LangChain imports

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from enum import Enum

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from src.api.health import deep_health
from src.api.rate_limit import enforce_client_rate_limit
from src.api.security import auth_required, verify_api_key
from src.config import is_production, settings
from src.guardrails import RateLimitError
from src.logging_config import setup_logging
from src.observability import init_langsmith_tracing
from src.runner import MODE_LABELS, run_agent

logger = logging.getLogger(__name__)


def _validate_production_config() -> None:
    """Refuse to start with an unsafe production configuration."""
    errors: list[str] = []
    if not settings.openai_api_key:
        errors.append("OPENAI_API_KEY is required in production")
    if auth_required() and not settings.api_key:
        errors.append("API_KEY must be set — authentication is mandatory in production")
    if settings.cors_origins.strip() == "*":
        logger.warning(
            "CORS_ORIGINS is '*' in production — set explicit origins to restrict browser access"
        )
    if errors:
        for e in errors:
            logger.error(e)
        raise RuntimeError("Unsafe production configuration: " + "; ".join(errors))


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_langsmith_tracing()
    if is_production():
        _validate_production_config()
    logger.info("Agentic RAG API started | env=%s", settings.environment)
    yield


app = FastAPI(
    title="Agentic RAG API",
    description="Production-grade Agentic RAG system",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS. Credentials are only allowed with an explicit origin list: the CORS
# spec forbids wildcard origins combined with credentials.
_wildcard = settings.cors_origins.strip() == "*"
_origins = ["*"] if _wildcard else [
    o.strip() for o in settings.cors_origins.split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=not _wildcard,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)


class AgentMode(str, Enum):
    baseline = "baseline"
    router = "router"
    crag = "crag"
    decompose = "decompose"
    multi_hop = "multi_hop"
    tools = "tools"
    agentic = "agentic"


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    mode: AgentMode = Field(default=AgentMode.agentic)
    session_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Optional session ID for persistent memory (Supabase)",
    )
    use_memory: bool = Field(
        default=True,
        description="Include prior conversation context when answering",
    )


class QueryResponse(BaseModel):
    question: str
    mode: str
    answer: str
    sources: list[str] = []
    route: str | None = None
    route_reason: str | None = None
    steps: list[str] = []
    latency_ms: float = 0.0
    session_id: str | None = None


async def _run_agent_with_timeout(
    question: str,
    mode: str,
    chat_history: list[dict[str, str]] | None = None,
    use_memory: bool = True,
):
    """Run sync agent in thread pool with timeout.

    Note: on timeout the worker thread is abandoned, but the OpenAI client
    carries its own hard timeout (openai_timeout_seconds), so abandoned work
    terminates instead of billing indefinitely.
    """
    return await asyncio.wait_for(
        asyncio.to_thread(
            run_agent,
            question,
            mode,
            chat_history=chat_history,
            use_memory=use_memory,
        ),
        timeout=settings.request_timeout_seconds,
    )


def _memory_active(use_memory: bool) -> bool:
    return use_memory and settings.memory_enabled


async def _resolve_chat_history(
    session_id: str | None,
    use_memory: bool,
) -> tuple[list[dict[str, str]] | None, str | None]:
    """Load history from Supabase when session_id is provided.

    Generates a server-side session ID when memory is active and the client
    did not supply one, so clients can't be handed guessable IDs.
    """
    if not _memory_active(use_memory):
        return None, session_id

    from src.memory.supabase_store import is_supabase_configured, load_messages

    if not is_supabase_configured():
        return None, session_id

    if not session_id:
        return None, uuid.uuid4().hex

    # Supabase client is synchronous — keep it off the event loop
    loaded = await asyncio.to_thread(load_messages, session_id)
    history = [{"role": m["role"], "content": m["content"]} for m in loaded]
    return history or None, session_id


async def _persist_exchange(
    session_id: str | None,
    question: str,
    answer: str,
    mode: str,
) -> None:
    if not session_id or not settings.memory_enabled:
        return

    from src.memory.supabase_store import is_supabase_configured, save_message

    if not is_supabase_configured():
        return

    await asyncio.to_thread(save_message, session_id, "user", question, mode)
    await asyncio.to_thread(save_message, session_id, "assistant", answer, mode)


@app.get("/health")
async def health_liveness() -> dict[str, str]:
    """Liveness probe — process is running."""
    return {"status": "healthy", "service": "agentic-rag"}


@app.get("/health/ready")
async def health_readiness() -> JSONResponse:
    """Readiness probe — dependencies available."""
    report = await asyncio.to_thread(deep_health)
    status_code = 200 if report["status"] in ("healthy", "degraded") else 503
    return JSONResponse(content=report, status_code=status_code)


@app.get("/modes")
async def list_modes(_: None = Depends(verify_api_key)) -> dict[str, str]:
    return MODE_LABELS


@app.post("/query", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    _auth: None = Depends(verify_api_key),
    _rate: None = Depends(enforce_client_rate_limit),
) -> QueryResponse:
    try:
        start = time.time()
        chat_history, session_id = await _resolve_chat_history(
            request.session_id,
            request.use_memory,
        )
        result = await _run_agent_with_timeout(
            request.question,
            request.mode.value,
            chat_history=chat_history,
            use_memory=_memory_active(request.use_memory),
        )
        elapsed = (time.time() - start) * 1000

        await _persist_exchange(
            session_id,
            request.question,
            result.answer,
            request.mode.value,
        )

        logger.info("Query processed | mode=%s | latency=%.0fms", request.mode.value, elapsed)

        return QueryResponse(
            question=request.question,
            mode=result.mode,
            answer=result.answer,
            sources=result.sources,
            route=result.route,
            route_reason=result.route_reason,
            steps=result.steps,
            latency_ms=elapsed,
            session_id=session_id,
        )
    except asyncio.TimeoutError as exc:
        logger.warning("Query timed out after %ss", settings.request_timeout_seconds)
        raise HTTPException(status_code=504, detail="Query timed out") from exc
    except RateLimitError as exc:
        logger.warning("Query rate-limited | %s", exc)
        raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": "60"}) from exc
    except ValueError as exc:
        logger.warning("Query rejected | error=%s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Query failed")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@app.post("/query/stream")
async def query_stream(
    request: QueryRequest,
    _auth: None = Depends(verify_api_key),
    _rate: None = Depends(enforce_client_rate_limit),
) -> StreamingResponse:
    async def event_generator():
        try:
            start = time.time()
            chat_history, session_id = await _resolve_chat_history(
                request.session_id,
                request.use_memory,
            )
            result = await _run_agent_with_timeout(
                request.question,
                request.mode.value,
                chat_history=chat_history,
                use_memory=_memory_active(request.use_memory),
            )

            for step in result.steps:
                yield f"data: {json.dumps({'type': 'step', 'content': step})}\n\n"

            yield f"data: {json.dumps({'type': 'answer', 'content': result.answer})}\n\n"
            elapsed = (time.time() - start) * 1000
            await _persist_exchange(
                session_id,
                request.question,
                result.answer,
                request.mode.value,
            )
            yield f"data: {json.dumps({'type': 'done', 'latency_ms': elapsed, 'session_id': session_id})}\n\n"
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Query timed out'})}\n\n"
        except RateLimitError as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        except ValueError as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        except Exception:
            logger.exception("Streaming query failed")
            yield f"data: {json.dumps({'type': 'error', 'message': 'Internal server error'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.api.server:app",
        host="0.0.0.0",
        port=8000,
        workers=settings.api_workers,
    )
