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
import hashlib
import json
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from enum import Enum
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from src.api.health import deep_health
from src.api.metrics import (
    metrics_payload,
    record_capacity_rejection,
    record_request,
)
from src.api.rate_limit import enforce_client_rate_limit
from src.api.security import (
    auth_required,
    verify_api_key,
    verify_metrics_access,
    verify_readiness_access,
)
from src.cache.redis_cache import get_idempotent_response, set_idempotent_response
from src.config import is_production, settings
from src.guardrails import RateLimitError
from src.logging_config import get_request_id, set_request_id, setup_logging
from src.observability import init_langsmith_tracing
from src.runner import MODE_LABELS, run_agent, stream_agent

logger = logging.getLogger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Accept/propagate X-Request-ID and bind it into logging context."""

    async def dispatch(self, request: Request, call_next):
        rid = (request.headers.get("x-request-id") or "").strip() or uuid.uuid4().hex
        set_request_id(rid)
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response


def _validate_production_config() -> None:
    """Refuse to start with an unsafe production configuration."""
    errors: list[str] = []
    if not settings.openai_api_key:
        errors.append("OPENAI_API_KEY is required in production")
    if auth_required() and not settings.api_key:
        errors.append("API_KEY must be set — authentication is mandatory in production")
    if settings.cors_origins.strip() == "*":
        errors.append(
            "CORS_ORIGINS='*' is not allowed in production — list explicit origins"
        )
    if settings.api_key and len(settings.api_key) < 32:
        errors.append("API_KEY must be at least 32 characters")

    # Budgets and rate limits live in-process unless Redis backs them. With
    # multiple workers that silently multiplies every configured ceiling.
    if settings.api_workers > 1 and (
        (settings.rate_limit_backend or "auto").strip().lower() == "memory"
    ):
        errors.append(
            f"API_WORKERS={settings.api_workers} with RATE_LIMIT_BACKEND=memory "
            "would give each worker its own rate/token budget — use redis"
        )

    if errors:
        for e in errors:
            logger.error(e)
        raise RuntimeError("Unsafe production configuration: " + "; ".join(errors))


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_langsmith_tracing()
    for warning in settings.deprecation_warnings:
        logger.warning("Deprecated configuration: %s", warning)
    if is_production():
        _validate_production_config()
    elif settings.cors_origins.strip() == "*":
        logger.warning(
            "CORS_ORIGINS is '*' — acceptable in development, rejected in production"
        )
    logger.info(
        "Agentic RAG API started | env=%s | workers=%d | max_concurrent=%d "
        "| privacy=in:%s/out:%s",
        settings.environment,
        settings.api_workers,
        settings.max_concurrent_queries,
        settings.privacy_input_mode,
        settings.privacy_output_mode,
    )
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
    allow_headers=[
        "Content-Type",
        "X-API-Key",
        "X-Request-ID",
        "Idempotency-Key",
    ],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(RequestIdMiddleware)

_trusted = [h.strip() for h in (settings.trusted_hosts or "").split(",") if h.strip()]
if _trusted:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_trusted)


class AgentMode(str, Enum):
    baseline = "baseline"
    router = "router"
    crag = "crag"
    decompose = "decompose"
    multi_hop = "multi_hop"
    tools = "tools"
    agentic = "agentic"
    consensus = "consensus"


class ChatTurnIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=8000)


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
    chat_history: list[ChatTurnIn] | None = Field(
        default=None,
        max_length=20,
        description="Prior turns from the client (used when Supabase is unavailable)",
    )
    tenant_id: str | None = Field(
        default="default",
        max_length=64,
        description="Tenant identifier for multi-tenant data isolation",
    )
    user_roles: list[str] = Field(
        default_factory=lambda: ["public"],
        description="Caller's authorized access groups/roles for RBAC document filtering",
    )


class CitationOut(BaseModel):
    index: int
    chunk_id: str
    source: str
    page: int | None = None
    section: str | None = None
    snippet: str = ""
    score: float | None = None


class QueryResponse(BaseModel):
    question: str
    mode: str
    answer: str
    sources: list[str] = []
    citations: list[CitationOut] = []
    route: str | None = None
    route_reason: str | None = None
    steps: list[str] = []
    follow_ups: list[str] = []
    latency_ms: float = 0.0
    session_id: str | None = None
    tenant_id: str | None = None
    consensus_score: float | None = None
    critique_summary: str | None = None
    error_code: str | None = None


# Hard ceiling on agent runs in flight. Without it, requests pile up behind the
# default thread pool and concurrent LLM spend is unbounded — a slow upstream
# turns into an unbounded queue instead of visible backpressure.
_query_semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_queries))


@asynccontextmanager
async def _concurrency_slot():
    """Acquire a run slot or fail fast with 503 rather than queueing forever."""
    try:
        await asyncio.wait_for(
            _query_semaphore.acquire(),
            timeout=settings.concurrency_acquire_timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        record_capacity_rejection()
        logger.warning(
            "Rejected request — %d concurrent slots all busy",
            settings.max_concurrent_queries,
        )
        raise HTTPException(
            status_code=503,
            detail="Server at capacity — retry shortly",
            headers={"Retry-After": "5"},
        ) from exc
    try:
        yield
    finally:
        _query_semaphore.release()


async def _run_agent_with_timeout(
    question: str,
    mode: str,
    chat_history: list[dict[str, str]] | None = None,
    use_memory: bool = True,
    rbac_context: Any | None = None,
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
            rbac_context=rbac_context,
        ),
        timeout=settings.request_timeout_seconds,
    )


def _memory_active(use_memory: bool) -> bool:
    return use_memory and settings.memory_enabled


async def _resolve_chat_history(
    session_id: str | None,
    use_memory: bool,
    client_history: list[ChatTurnIn] | None = None,
) -> tuple[list[dict[str, str]] | None, str | None]:
    """Resolve conversation history for memory-augmented answers.

    Preference order when memory is active:
    1. Client-provided chat_history (browser apps / local chat store)
    2. Supabase session history when configured
    """
    if not _memory_active(use_memory):
        return None, session_id

    if client_history:
        history = [{"role": m.role, "content": m.content} for m in client_history]
        return history or None, session_id

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
async def health_readiness(
    _auth: None = Depends(verify_readiness_access),
) -> JSONResponse:
    """Readiness probe — dependencies available.

    Auth-gated by default (``PROTECT_READINESS_ENDPOINT``): the report names the
    Chroma host/port, indexed document count, and which providers are wired.
    Kubernetes-style probes should use ``/health`` or supply the API key.
    """
    report = await asyncio.to_thread(deep_health)
    status_code = 200 if report["status"] in ("healthy", "degraded") else 503
    return JSONResponse(content=report, status_code=status_code)


@app.get("/metrics")
async def prometheus_metrics(
    _auth: None = Depends(verify_metrics_access),
) -> Response:
    """Prometheus scrape endpoint.

    Auth-gated by default (``PROTECT_METRICS_ENDPOINT``); point Prometheus at it
    with an ``X-API-Key`` header, or disable the gate when the network layer
    already restricts access.
    """
    payload, content_type = metrics_payload()
    return Response(content=payload, media_type=content_type)


@app.get("/modes")
async def list_modes(_: None = Depends(verify_api_key)) -> dict[str, str]:
    return MODE_LABELS


def _request_body_hash(request: QueryRequest) -> str:
    payload = request.model_dump(mode="json")
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@app.post("/query", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    _auth: None = Depends(verify_api_key),
    _rate: None = Depends(enforce_client_rate_limit),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> QueryResponse:
    body_hash = _request_body_hash(request)
    if idempotency_key:
        cached = get_idempotent_response(idempotency_key)
        if cached is not None:
            if cached.get("body_hash") != body_hash:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency-Key reused with a different request body",
                )
            record_request(request.mode.value, "query", "idempotent", 0.0)
            return QueryResponse(**cached["response"])

    status = "ok"
    start = time.time()
    try:
        from src.schemas import RBACContext

        rbac = RBACContext(
            tenant_id=request.tenant_id or "default",
            user_roles=request.user_roles or ["public"],
        )
        chat_history, session_id = await _resolve_chat_history(
            request.session_id,
            request.use_memory,
            client_history=request.chat_history,
        )
        async with _concurrency_slot():
            result = await _run_agent_with_timeout(
                request.question,
                request.mode.value,
                chat_history=chat_history,
                use_memory=_memory_active(request.use_memory),
                rbac_context=rbac,
            )
        elapsed = (time.time() - start) * 1000

        await _persist_exchange(
            session_id,
            request.question,
            result.answer,
            request.mode.value,
        )

        logger.info(
            "Query processed | mode=%s | tenant=%s | latency=%.0fms | history_turns=%d | request_id=%s",
            request.mode.value,
            rbac.tenant_id,
            elapsed,
            len(chat_history or []),
            get_request_id(),
        )

        response = QueryResponse(
            question=request.question,
            mode=result.mode,
            answer=result.answer,
            sources=result.sources,
            citations=[CitationOut(**c.to_dict()) for c in (result.citations or [])],
            route=result.route,
            route_reason=result.route_reason,
            steps=result.steps,
            follow_ups=result.follow_ups,
            latency_ms=elapsed,
            session_id=session_id,
            tenant_id=result.tenant_id or rbac.tenant_id,
            consensus_score=getattr(result, "consensus_score", None),
            critique_summary=getattr(result, "critique_summary", None),
            error_code=result.error_code,
        )
        if idempotency_key:
            set_idempotent_response(
                idempotency_key,
                body_hash,
                response.model_dump(mode="json"),
            )
        record_request(request.mode.value, "query", status, elapsed / 1000.0)
        return response
    except asyncio.TimeoutError as exc:
        status = "timeout"
        record_request(request.mode.value, "query", status, time.time() - start)
        logger.warning("Query timed out after %ss", settings.request_timeout_seconds)
        raise HTTPException(status_code=504, detail="Query timed out") from exc
    except RateLimitError as exc:
        status = "rate_limited"
        record_request(request.mode.value, "query", status, time.time() - start)
        logger.warning("Query rate-limited | %s", exc)
        raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": "60"}) from exc
    except ValueError as exc:
        status = "rejected"
        record_request(request.mode.value, "query", status, time.time() - start)
        logger.warning("Query rejected | error=%s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        status = "error"
        record_request(request.mode.value, "query", status, time.time() - start)
        logger.exception("Query failed")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@app.post("/query/stream")
async def query_stream(
    request: QueryRequest,
    _auth: None = Depends(verify_api_key),
    _rate: None = Depends(enforce_client_rate_limit),
) -> StreamingResponse:
    """SSE stream of agent steps + answer tokens as they are produced."""

    async def event_generator():
        from src.schemas import RBACContext

        rbac = RBACContext(
            tenant_id=request.tenant_id or "default",
            user_roles=request.user_roles or ["public"],
        )
        start = time.time()
        chat_history, session_id = await _resolve_chat_history(
            request.session_id,
            request.use_memory,
            client_history=request.chat_history,
        )
        use_memory = _memory_active(request.use_memory)
        final_answer = ""
        loop = asyncio.get_running_loop()
        event_queue: asyncio.Queue[dict | None] = asyncio.Queue()
        # Worker threads cannot be cancelled, so signal them cooperatively.
        cancelled = threading.Event()
        # Total wall-clock budget. request_timeout_seconds only bounds the gap
        # between events; without this a slow-but-steady stream never ends.
        deadline = start + settings.stream_timeout_seconds

        def _produce() -> None:
            try:
                for event in stream_agent(
                    request.question,
                    request.mode.value,
                    chat_history=chat_history,
                    use_memory=use_memory,
                    cancelled=cancelled,
                    rbac_context=rbac,
                ):
                    loop.call_soon_threadsafe(event_queue.put_nowait, event)
            except Exception:
                logger.exception("stream_agent producer failed")
                loop.call_soon_threadsafe(
                    event_queue.put_nowait,
                    {"type": "error", "message": "Internal server error"},
                )
            finally:
                loop.call_soon_threadsafe(event_queue.put_nowait, None)

        async with _concurrency_slot():
            producer = asyncio.create_task(asyncio.to_thread(_produce))

            try:
                while True:
                    gap_budget = float(settings.request_timeout_seconds)
                    total_budget = deadline - time.time()
                    if total_budget <= 0:
                        cancelled.set()
                        record_request(
                            request.mode.value,
                            "query_stream",
                            "timeout",
                            time.time() - start,
                        )
                        yield f"data: {json.dumps({'type': 'error', 'message': 'Query exceeded maximum duration'})}\n\n"
                        break

                    try:
                        event = await asyncio.wait_for(
                            event_queue.get(),
                            timeout=min(gap_budget, total_budget),
                        )
                    except asyncio.TimeoutError:
                        cancelled.set()
                        record_request(
                            request.mode.value,
                            "query_stream",
                            "timeout",
                            time.time() - start,
                        )
                        yield f"data: {json.dumps({'type': 'error', 'message': 'Query timed out'})}\n\n"
                        break

                    if event is None:
                        break

                    if event.get("type") == "answer":
                        final_answer = str(event.get("content") or "")

                    if event.get("type") == "done":
                        elapsed = (time.time() - start) * 1000
                        if final_answer:
                            await _persist_exchange(
                                session_id,
                                request.question,
                                final_answer,
                                request.mode.value,
                            )
                        event = {
                            **event,
                            "latency_ms": elapsed,
                            "session_id": session_id,
                        }
                        record_request(
                            request.mode.value,
                            "query_stream",
                            "ok",
                            elapsed / 1000.0,
                        )

                    yield f"data: {json.dumps(event, default=str)}\n\n"

                    if event.get("type") == "error":
                        record_request(
                            request.mode.value,
                            "query_stream",
                            "error",
                            time.time() - start,
                        )
                        break
            finally:
                # Covers client disconnect (GeneratorExit) as well as normal
                # completion — always release the worker before the slot.
                cancelled.set()
                if not producer.done():
                    producer.cancel()
                    try:
                        await producer
                    except asyncio.CancelledError:
                        pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Phase 12: Asynchronous Ingestion Job Endpoints
# ---------------------------------------------------------------------------


class IngestJobRequest(BaseModel):
    source_paths: list[str] = Field(
        ...,
        min_length=1,
        description="List of file paths or directories to ingest into the vector store",
    )
    tenant_id: str = Field(
        default="default",
        description="Tenant identifier for multi-tenant data isolation",
    )
    access_groups: list[str] = Field(
        default_factory=lambda: ["public"],
        description="Authorized user access groups for document RBAC",
    )
    webhook_url: str | None = Field(
        default=None,
        description="Optional HTTP(S) URL to receive a POST webhook notification upon job completion",
    )


class IngestJobResponse(BaseModel):
    job_id: str
    status: str
    source_paths: list[str] = []
    tenant_id: str = "default"
    access_groups: list[str] = []
    progress_pct: float
    total_files: int
    processed_files: int
    total_chunks: int
    error: str | None = None
    webhook_url: str | None = None
    created_at: float
    completed_at: float | None = None


@app.post("/ingest/jobs", response_model=IngestJobResponse, status_code=202)
async def submit_ingest_job(
    request: IngestJobRequest,
    _auth: None = Depends(verify_api_key),
) -> IngestJobResponse:
    """Submit a document ingestion job to the asynchronous background worker queue."""
    from src.ingestion.queue import get_ingestion_queue

    queue = get_ingestion_queue()
    job = queue.submit_job(
        source_paths=request.source_paths,
        tenant_id=request.tenant_id,
        access_groups=request.access_groups,
        webhook_url=request.webhook_url,
    )
    return IngestJobResponse(**job.to_dict())


@app.get("/ingest/jobs/{job_id}", response_model=IngestJobResponse)
async def get_ingest_job(
    job_id: str,
    _auth: None = Depends(verify_api_key),
) -> IngestJobResponse:
    """Poll progress and completion status of an ingestion job."""
    from src.ingestion.queue import get_ingestion_queue

    job = get_ingestion_queue().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Ingestion job '{job_id}' not found")
    return IngestJobResponse(**job.to_dict())


@app.get("/ingest/jobs", response_model=list[IngestJobResponse])
async def list_ingest_jobs(
    limit: int = 50,
    _auth: None = Depends(verify_api_key),
) -> list[IngestJobResponse]:
    """List recent ingestion jobs."""
    from src.ingestion.queue import get_ingestion_queue

    jobs = get_ingestion_queue().list_jobs(limit=min(100, max(1, limit)))
    return [IngestJobResponse(**j.to_dict()) for j in jobs]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.api.server:app",
        host="0.0.0.0",
        port=8000,
        workers=settings.api_workers,
    )
