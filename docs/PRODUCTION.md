# Production Deployment Guide

This document covers deploying Agentic RAG to production: local run, Docker, CI/CD, and
the operational checklist to work through before your first real deploy.

## Local Run

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env with your OPENAI_API_KEY, NVIDIA_API_KEY, and optional settings:
#   CHUNKING_STRATEGY=section_parent_child  # or 'fixed' for legacy behavior
#   CLEANSE_ENABLED=true                    # remove headers/footers/boilerplate
#   RETRIEVAL_SEARCH_TYPE=hybrid            # hybrid (RRF dense+BM25), mmr, or similarity
#   RETRIEVAL_TOP_K=6                       # final chunks passed to LLM
#   RETRIEVAL_CANDIDATE_K=20                # over-fetch before rerank
#   RERANK_PROVIDER=nvidia                  # nvidia | flashrank
#   RERANK_MODEL=nvidia/llama-nemotron-rerank-vl-1b-v2
#   NVIDIA_API_KEY=nvapi-...                # from https://build.nvidia.com
#   GROQ_API_KEY=...                        # optional OpenAI failover
#   CACHE_ENABLED=true + REDIS_URL=...      # optional answer cache
#   RATE_LIMIT_BACKEND=auto                 # auto | redis | memory
#   QUALITY_GUARDRAILS_ENABLED=false        # enable extra LLM quality checks
#   MULTI_SOURCE_ENABLED=true               # federate SQLite / ops API / lab MCP
#   EXTRA_SOURCES=database,api,mcp

# 2. Ingest the knowledge base (one-time, or whenever the corpus changes)
# For structured PDFs (rag.pdf): uses TOC/heading-aware parent-child chunking
# For unstructured docs: falls back to regex heading detection, then fixed-size chunks
python -m src.ingestion.ingest --source data/sample_docs

# 3. Start the API server
uvicorn src.api.server:app --host 0.0.0.0 --port 8000

# 4. Test it
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is Self-RAG?", "mode": "agentic"}'
```

If `REQUIRE_API_KEY=true` (mandatory once `ENVIRONMENT=production`, see below), add
`-H "X-API-Key: your-key"` to every request except `/health`.

### Run Evaluation

```bash
# Offline golden-set schema/keyword gate (CI — no embeddings)
python -m src.evaluation.retrieval_metrics --offline

# Live retrieval metrics vs data/eval/golden_qa.json
python -m src.evaluation.retrieval_metrics

# RAGAS-inspired LLM-judge across all 8 modes → ragas_eval_results.json
python -m src.evaluation.evaluate_all_modes
```

## Docker Deployment

### Build & Run

```bash
docker build -t agentic-rag:latest .

docker run -p 8000:8000 \
  -e OPENAI_API_KEY=sk-... \
  -e NVIDIA_API_KEY=nvapi-... \
  -e RERANK_PROVIDER=nvidia \
  -e RERANK_MODEL=nvidia/llama-nemotron-rerank-vl-1b-v2 \
  -e ENVIRONMENT=production \
  -e API_KEY=your-long-random-secret \
  -v ./data/chroma_db:/data/chroma_db \
  agentic-rag:latest
```

The image (`Dockerfile`):
- **Multi-stage**: wheels are compiled in a builder stage, so `gcc` never ships in the runtime image.
- Installs dependencies **before** copying application code, so code changes don't bust the dependency layer.
- Runs as a **non-root** user (`appuser`); application code is owned by root, so the running process cannot rewrite it.
- Excludes secrets and dev artifacts via `.dockerignore` — `.env`, `.git`, `tests/`, `docs/`, `data/` never end up in the image.
- Ships a `HEALTHCHECK` hitting `/health` (liveness).

CI fails the build if the image contains a `.env` file, runs as root, or still has a
compiler in it.

### Docker Compose (Recommended)

```bash
# 1. Configure application secrets (never commit this file)
cp .env.production.example .env.production
chmod 600 .env.production
# Edit with real OPENAI_API_KEY, NVIDIA_API_KEY, API_KEY, GROQ_API_KEY, etc.

# 2. Configure the infrastructure secrets compose reads from the shell.
#    Compose fails fast if any of these is missing.
cat > .env <<EOF
REDIS_PASSWORD=$(openssl rand -hex 24)
API_KEY=<the same API_KEY you set in .env.production>
GRAFANA_ADMIN_PASSWORD=$(openssl rand -hex 16)
EOF
chmod 600 .env

# Core stack: Redis + Chroma HTTP + API + nginx frontend
docker compose up -d --build

# Optional observability
docker compose up prometheus grafana -d

# Logs / stop
docker compose logs -f agentic-rag
docker compose down
```

| Service | Published port | Role |
|---------|----------------|------|
| `agentic-rag` | **8000** | FastAPI (`CHROMA_MODE=http`, `CACHE_ENABLED=true`, `RATE_LIMIT_BACKEND=redis`) |
| `frontend` | **8080** | nginx React UI; proxies `/api` and injects `API_KEY` server-side |
| `redis` | internal only | Answer cache, shared rate limits, budgets, idempotency |
| `chroma` | internal only | Persistent Chroma HTTP server |
| `prometheus` | internal only | Scrapes API `/metrics` (optional) |
| `grafana` | internal only | Pre-provisioned **Agentic RAG Overview** dashboard (optional) |

**Only the API and the frontend are published to the host.** Redis, Chroma, Prometheus,
and Grafana are reachable only on the internal compose network — publishing them exposes
unauthenticated data stores and dashboards to anything that can reach the host. Redis
requires a password; Grafana requires an admin password (there is no `admin/admin`
fallback). To reach Grafana, tunnel instead of publishing:

```bash
docker compose exec grafana true            # confirm it's up
ssh -L 3000:localhost:3000 user@your-host   # then browse http://localhost:3000
```

The container healthcheck uses `/health` (liveness), because `/health/ready` is
auth-gated. Sample docs are mounted read-only at `/app/data/sample_docs`; Chroma data
lives in the `chroma_data` volume and Redis in `redis_data`.

Inside compose the stack sets `PROTECT_METRICS_ENDPOINT=false`: no host port is
published, so network isolation is the control and Prometheus can scrape without a key.
Running the API outside compose? Leave the default (`true`) and give your scraper an
`X-API-Key` header.

## API Endpoints

### Liveness

```bash
GET /health
→ {"status": "healthy", "service": "agentic-rag"}
```

Always returns 200 if the process is running. Unauthenticated. Use for container
orchestrator liveness probes (restart-if-failing).

### Readiness

```bash
GET /health/ready
→ {
  "status": "healthy" | "degraded" | "unhealthy",
  "service": "agentic-rag",
  "environment": "production",
  "checks": {
    "chroma": {"status": "ok", "detail": "136 documents indexed"},
    "openai": {"status": "ok", "detail": "API key configured"},
    "data_dir": {"status": "ok", "detail": "/data/chroma_db"},
    "extra_sources": {"status": "ok", "detail": "db papers=3; api systems=3; mcp tools=3"}
  }
}
```

Returns 503 when `unhealthy`. Checks the vector store, OpenAI key configuration, data
directory, Redis (when required), extra sources (SQLite/API/MCP), and optional Groq/NVIDIA.

**Auth-gated by default** (`PROTECT_READINESS_ENDPOINT=true`): the report names the
Chroma host/port, the indexed document count, and which providers are wired, which is
free reconnaissance for an attacker. Send `X-API-Key`, or point orchestrator readiness
probes at `/health` instead. Error details stay generic (exception class name only) — check
logs for specifics.

When no `API_KEY` is configured at all the gate falls open so local probes keep working;
in production that cannot happen, because startup refuses to run without a key.

### Sample ops catalog & lab MCP (authenticated)

Demo knowledge that is **not** in `rag.pdf`. Same `X-API-Key` gate as `/query` when auth is on.

```bash
GET /kb/v1/search?q=retriever-prod
GET /kb/v1/systems/retriever-prod
GET /kb/v1/glossary/index_lag
GET /kb/v1/incidents/INC-1042

POST /mcp
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"get_experiment","arguments":{"id":"exp-42"}}}
```

stdio MCP (Cursor / Claude Desktop): `python -m src.sources.mcp_server`.
Disable federation with `MULTI_SOURCE_ENABLED=false`.

### List Modes (authenticated)

```bash
GET /modes
→ {"baseline": "Phase 1 — Baseline RAG", ...}
```

### Query (Synchronous, authenticated + rate-limited)

```bash
POST /query
-H "X-API-Key: your-key"   # required when REQUIRE_API_KEY=true / ENVIRONMENT=production

{
  "question": "What is Self-RAG?",
  "mode": "agentic",
  "session_id": "optional-8-to-64-char-id",
  "use_memory": true
}

→ {
  "question": "...",
  "mode": "agentic",
  "answer": "...",
  "sources": ["data/sample_docs/rag.pdf"],
  "route": "retrieve",
  "route_reason": "...",
  "steps": ["Router → retrieve", "Strategy: simple", ...],
  "latency_ms": 5234.0,
  "session_id": "..."
}
```

Possible error responses: `400` (guardrail rejection), `401` (missing/invalid API key),
`429` (rate limit — see [GUARDRAILS.md](GUARDRAILS.md)), `504` (timed out), `500`
(unexpected failure — details are logged server-side, not returned to the client).

### Metrics (Prometheus)

```bash
GET /metrics
# rag_requests_total{mode,endpoint,status}
# rag_request_latency_seconds{mode,endpoint}
# rag_cache_events_total{event=hit|write}
# rag_llm_fallback_total
# rag_rate_limit_total
# rag_capacity_rejections_total          — 503s from the concurrency ceiling
# rag_node_gate_total{result}            — poison containment (quarantine|abort)
# rag_tokens_total{provider,direction}   — token consumption
# rag_cost_usd_total{provider}           — estimated spend
```

**Auth-gated by default** (`PROTECT_METRICS_ENDPOINT=true`) — send `X-API-Key`, or set it
to `false` when the network layer already restricts access (that is what the compose stack
does, since no host port is published).

Cost is a first-class operational concern here, so token counts and estimated spend are
exported as counters rather than only appearing in logs. Estimates use the configured
per-token rates (`COST_PER_1K_*_USD`, `GROQ_COST_PER_1K_*_USD`) — they are approximations,
not billing data. See **Observability** below for the Grafana dashboard.

### Query (Streaming)

True progressive SSE — agent **steps** as LangGraph nodes finish, **tokens** as the
final answer generates, then follow-ups / sources / done. The React UI uses this by
default (`frontend/src/hooks/useChat.ts` → `streamQuery`). Sync `POST /query` remains
for CLI, evals, and simple clients.

```bash
POST /query/stream
# Event types: step | token | answer | follow_ups | sources | done | error
curl -N http://localhost:8000/query/stream \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is Self-RAG?", "mode": "agentic"}'
```

Example frames:

```text
data: {"type": "step", "content": "Router → retrieve: …"}
data: {"type": "step", "content": "Simple retrieval: fetched 6 chunks"}
data: {"type": "token", "content": "Self"}
data: {"type": "token", "content": "-RAG"}
data: {"type": "answer", "content": "Self-RAG is …"}
data: {"type": "follow_ups", "content": ["…", "…", "…"]}
data: {"type": "sources", "content": ["rag.pdf#p2"], "citations": […]}
data: {"type": "done", "latency_ms": 4200, "session_id": "…", "mode": "agentic"}
```

### Asynchronous Document Ingestion Queue & Webhooks

For background document ingestion of heavy PDF batches without HTTP timeouts:

```bash
# Submit Ingestion Job (HTTP 202 Accepted)
curl -X POST http://localhost:8000/ingest/jobs \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "source_paths": ["data/sample_docs/rag.pdf"],
    "tenant_id": "enterprise_corp",
    "access_groups": ["research", "admin"],
    "webhook_url": "https://api.yourdomain.com/webhooks/ingest"
  }'

# Poll Job Status & Progress
curl -X GET http://localhost:8000/ingest/jobs/{job_id} \
  -H "X-API-Key: your-key"
```

Webhooks dispatch `POST` requests signed with `X-Hub-Signature-256: sha256=...` HMAC authentication using `WEBHOOK_SECRET`.

## Security Checklist (Non-Negotiable)

**Enforced by the code** — `src/api/server.py::_validate_production_config` refuses to
start when `ENVIRONMENT=production` and any of these is wrong:

- [ ] `OPENAI_API_KEY` is set
- [ ] `API_KEY` is set and **at least 32 characters** (`openssl rand -hex 32`), not the placeholder
- [ ] `CORS_ORIGINS` lists your actual frontend origin(s) — `*` is **rejected**, not warned
- [ ] `API_WORKERS > 1` only with `RATE_LIMIT_BACKEND=redis` — in-memory budgets give every worker its own ceiling, silently multiplying your spend cap

**Enforced by CI** — the `docker` and `security` jobs fail on:

- [ ] A `.env` file inside the built image
- [ ] A container running as root
- [ ] A compiler present in the runtime image
- [ ] Known CVEs in Python deps (`pip-audit`), npm deps (`npm audit`), or the image (Trivy)
- [ ] Secrets anywhere in git history (`gitleaks`)

**Your responsibility:**

- [ ] Secrets rotated if ever pasted into a doc, screenshot, or chat — plaintext exposure anywhere means "compromised," even in a private repo
- [ ] `.env` / `.env.production` are `chmod 600` and gitignored (`git check-ignore .env .env.production`; `deploy.sh` refuses a group/world-readable file)
- [ ] `REDIS_PASSWORD` and `GRAFANA_ADMIN_PASSWORD` set — compose will not start without them
- [ ] TLS terminates in front of the stack, and the HSTS header in `frontend/nginx.conf` is uncommented
- [ ] `TRUSTED_HOSTS` set, and `TRUST_PROXY_HEADERS=true` **only** when a proxy you control rewrites `X-Forwarded-For` (otherwise clients can spoof their rate-limit identity)
- [ ] `docs/supabase_schema.sql` applied if memory is enabled — it turns on RLS and installs the retention sweep
- [ ] Load test run against a staging copy (`pip install -r requirements-load.txt && locust -f tests/load/locustfile.py`) to confirm the limits behave under saturation

## Production Checklist

### Ingestion & Retrieval
- [ ] `CHUNKING_STRATEGY` selected: `section_parent_child` (recommended for structured PDFs) or `fixed` (legacy)
- [ ] `CLEANSE_ENABLED` and cleanse settings tuned (drop headers/footers, irrelevant sections, etc.)
- [ ] `RETRIEVAL_SEARCH_TYPE` set appropriately: `hybrid` (dense + BM25), `mmr`, or `similarity`
- [ ] `RETRIEVAL_TOP_K` tuned (5–7 for broader coverage) — final chunks after rerank
- [ ] `RETRIEVAL_CANDIDATE_K` set (typically 20) — over-fetch pool before cross-encoder rerank
- [ ] `RERANK_ENABLED=true` and `RERANK_PROVIDER` set (`nvidia` recommended, or `flashrank` for offline)
- [ ] When using NVIDIA: `NVIDIA_API_KEY` set and `RERANK_MODEL` matches your keyed model (default `nvidia/llama-nemotron-rerank-vl-1b-v2`)
- [ ] Knowledge base ingested with `python -m src.ingestion.ingest --source YOUR_DOCS`
- [ ] Extra sources: `MULTI_SOURCE_ENABLED` and `EXTRA_SOURCES` (SQLite catalog seeds on API startup; `/kb` and `/mcp` are demo knowledge, not live production systems)

### Agent & Guardrails
- [ ] `GRADER_RELEVANCE_THRESHOLD` tuned (0.6–0.7 for stricter filtering, 0.3–0.5 for lenient)
- [ ] `MAX_RETRIEVAL_RETRIES` set (typically 2) for failed retrieval loops (CRAG, multi-hop)
- [ ] `QUALITY_GUARDRAILS_ENABLED` set: `true` for extra LLM quality checks (slower) or `false` for speed
- [ ] `MAX_QUERIES_PER_MINUTE_PER_CLIENT`, `MAX_TOKENS_PER_MINUTE`, `MAX_TOKENS_PER_HOUR` set to budget (see [GUARDRAILS.md](GUARDRAILS.md))

### LLM & Cost Control
- [ ] `OPENAI_API_KEY` set to a production key with billing limits configured on the OpenAI dashboard
- [ ] `OPENAI_MODEL` set appropriately for your cost/quality tradeoff
- [ ] Optional: `GROQ_API_KEY` + `LLM_FALLBACK_ENABLED=true` for automatic failover
- [ ] `COST_PER_1K_INPUT_USD` and `COST_PER_1K_OUTPUT_USD` match your actual model (verify on OpenAI pricing)
- [ ] `OPENAI_TIMEOUT_SECONDS` and `REQUEST_TIMEOUT_SECONDS` set long enough for slowest modes (decompose/multi_hop can take 10+ sec)

### Cache, Rate Limits & Resilience
- [ ] Redis reachable; `REDIS_URL` correct for your network (`redis://redis:6379/0` in compose)
- [ ] `CACHE_ENABLED` decided (compose defaults to `true`); re-ingest flushes answer keys
- [ ] `RATE_LIMIT_BACKEND=redis` (or `auto`) before running multiple `API_WORKERS`
- [ ] Circuit breaker thresholds acceptable (`CIRCUIT_BREAKER_FAILURE_THRESHOLD`, `CIRCUIT_BREAKER_RECOVERY_SECONDS`)

### Memory & Observability
- [ ] `MEMORY_ENABLED` set (true by default); memory packing params (`MEMORY_MAX_TURNS`, `MEMORY_RECENT_EXCHANGES`, etc.) tuned
- [ ] `SUPABASE_URL` / `SUPABASE_KEY` set if persistent cross-session memory needed; otherwise blank
- [ ] Prometheus/Grafana running if you want dashboards (`docker compose up prometheus grafana -d`)
- [ ] LangSmith tracing enabled if desired (`LANGSMITH_TRACING=true` — see [LANGSMITH_TRACING.md](LANGSMITH_TRACING.md))

### Testing & Deployment
- [ ] Golden-set gate passes (`python -m src.evaluation.retrieval_metrics --offline`)
- [ ] Evaluation suite run and reviewed (`python -m src.evaluation.evaluate_all_modes`)
- [ ] Test suite and lint pass (`pytest tests/ -q && ruff check src/ tests/`) — CI runs both automatically
- [ ] Streaming endpoint tested for your longest expected queries
- [ ] Knowledge base re-ingested after any corpus updates (parents + children refreshed; answer cache flushed)

## CI/CD

`.github/workflows/ci.yml` runs on every push/PR to `main`/`master`/`dev`/`prod`:

| Job | What it does |
|-----|--------------|
| `lint` | `ruff check` with the version pinned in `requirements-dev.txt` and the rule set pinned in `pyproject.toml` |
| `test` | `pytest` with coverage gate (`--cov-fail-under`), import smoke test, `retrieval_metrics --offline` |
| `security` | `pip-audit` on pinned deps + `gitleaks` over full git history |
| `frontend` | `npm ci`, `npm run lint`, `npm audit --audit-level=high`, production Vite build |
| `docker` | Builds the image, then asserts: no `.env` inside, non-root user, no compiler, no CRITICAL/HIGH CVEs (Trivy) |

Both the linter and the scanners are **pinned**. An unpinned tool turns CI red on someone
else's release day, and the failure has nothing to do with your change.

The coverage gate is a **ratchet floor**, set just below the current number so coverage
can only go up. Raise it in `ci.yml` whenever the measured value clears the next step.

`.github/workflows/nightly-eval.yml` runs separately on a schedule: it ingests the corpus
and scores real retrieval against `data/eval/golden_qa.json`, failing on regression in
recall@k, MRR, or hit rate. The CI gate only validates the golden file's *schema* offline,
so without this a chunking or reranker change could tank retrieval quality while CI stayed
green.

`.github/dependabot.yml` opens grouped weekly PRs for pip, npm, Docker, and Actions —
pinning everything is only safe if something tells you when a pin goes stale.

Recommended branch flow (see root [README.md](../README.md#branching)):
- `dev` — default branch, all day-to-day work lands here; CI runs on every push.
- `prod` — protected; only updated via a reviewed PR from `dev` once CI is green. This
  makes every production release traceable to a specific PR diff.

## Monitoring & Cost

### Latency by Mode

Approximate, from `python -m src.evaluation.evaluate_all_modes` (varies with model,
corpus size, network latency, and whether NVIDIA rerank is enabled):

| Mode | Typical Latency |
|------|------------------|
| `baseline` | ~1–3s (retrieve + rerank + generation) |
| `router` | ~2–4s (routing overhead) |
| `crag` | ~3–6s (grading + possible retry) |
| `decompose` | ~4–8s (parallel sub-retrievals + synthesis) |
| `multi_hop` | ~5–10s (sequential retrieval loop) |
| `tools` | ~2–5s (function calling) |
| `agentic` | ~3–10s (strategy-dependent — picks one of the above internally) |

NVIDIA rerank typically adds a few hundred ms per retrieve call (one HTTP round-trip over
`candidate_k` passages). Use `RERANK_PROVIDER=flashrank` for offline/local latency, or
`RERANK_ENABLED=false` when benchmarking first-stage retrieval alone.

Run the eval suite against your own corpus and model for numbers that actually apply to
your deployment — the above are illustrative, not guarantees.

### Cost per Query

Token usage is tracked automatically per query (`src/guardrails.py::CostGuardrails`,
wired into `src/runner.py`) using LangChain's OpenAI callback — not an estimate. Every
query logs:

```
Token usage | mode=agentic | prompt=842 | completion=310 | cost=$0.00032
```

Default pricing assumes `gpt-4o-mini` (`COST_PER_1K_INPUT_USD=0.00015`,
`COST_PER_1K_OUTPUT_USD=0.0006`) — update these in `.env` if you use a different model, or
costs reported by `CostGuardrails.calculate_cost()` will be wrong. Cross-check against the
OpenAI billing dashboard or LangSmith periodically.

### Logs

Structured logs go to stdout/stderr (`src/logging_config.py`) — INFO level in production,
DEBUG in development. Pipe to CloudWatch, Stackdriver, Datadog, or an ELK stack as
appropriate for your infrastructure.

## Response Caching (Redis)

Identical `question` + `mode` pairs can be served from Redis for **1 hour** without
re-running retrieval/LLM. Wired in `src/runner.py` via `src/cache/redis_cache.py`.

```bash
CACHE_ENABLED=true
REDIS_URL=redis://localhost:6379/0   # docker-compose: redis://redis:6379/0
CACHE_TTL_SECONDS=3600
```

`docker-compose.yml` starts a `redis` service and sets `REDIS_URL` for the API.

**When caching applies**
- Same normalized question (whitespace/case-insensitive) + same mode
- No conversation history (`use_memory` with non-empty `chat_history` skips cache)

**When it does not**
- Memory-augmented multi-turn chats (answers depend on prior turns)
- Cache disabled or Redis unreachable (app continues without cache)
- Intermediate LangGraph node state is **not** stored in Redis — that would add
  latency; in-process state stays for speed. Redis here is for final answers only.

Cache hits appear as a `cache_hit` step in the response. Re-ingest **flushes**
`rag:v1:*` keys via `flush_answer_cache()` so stale answers are not served after
a corpus update (TTL remains a backstop).

## Capacity & Backpressure

Timeouts alone do not bound cost. Three limits work together:

| Setting | Bounds | Failure mode when hit |
|---|---|---|
| `MAX_CONCURRENT_QUERIES` (default 8) | Agent runs in flight | `503` + `Retry-After: 5` after `CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS` |
| `REQUEST_TIMEOUT_SECONDS` (120) | One `POST /query`; the gap between SSE events | `504` (sync) or an `error` event (stream) |
| `STREAM_TIMEOUT_SECONDS` (300) | Total wall-clock for one SSE run | `error` event, worker cancelled |

Without the concurrency ceiling, a slow upstream turns into an unbounded queue behind the
thread pool and unbounded concurrent LLM spend. Fast `503`s are the correct behaviour
under saturation — that is visible backpressure rather than silent queueing. Watch
`rag_capacity_rejections_total`: sustained non-zero means scale out or raise the ceiling.

`STREAM_TIMEOUT_SECONDS` exists because `REQUEST_TIMEOUT_SECONDS` only bounds the *gap*
between events — a slow-but-steady stream would otherwise never time out.

Worker threads cannot be killed, so client disconnect is handled cooperatively: the
generator sets a cancel flag, and the emitter raises at the next event boundary. That
raise is a `BaseException` subclass (`src.streaming.CancelledRun`) precisely so the broad
`except Exception` handlers in the graph nodes cannot swallow it and keep billing.

## Circuit Breakers

NVIDIA rerank and DuckDuckGo web search are wrapped in in-process circuit breakers
(`src/resilience/circuit_breaker.py`). After `CIRCUIT_BREAKER_FAILURE_THRESHOLD`
consecutive failures (default 5), calls short-circuit for
`CIRCUIT_BREAKER_RECOVERY_SECONDS` (default 60), then allow a half-open trial.

When the rerank breaker is open, retrieval continues with first-stage ranking only.
When the web-search breaker is open, the tool returns a `[CIRCUIT_OPEN]` sentinel that
node gates quarantine (see below) so error text cannot be treated as evidence.

## Node Output Gates (Poison Containment)

Infra breakers stop *calling* a dead upstream. **Node gates** stop *bad data* from one
graph node or tool from contaminating the next (`src/resilience/node_gate.py`).

| Severity | When | Effect |
|----------|------|--------|
| `ok` | Contract satisfied | Result enters state as usual |
| `quarantine` | Optional tool failure / empty / circuit open | Discard as evidence; tell the LLM it is not factual content; after 3 tool quarantines in one tools loop → abort |
| `abort` | Critical path broken (invalid route/strategy, empty required answer, grader/router exception, web-only path with poisoned context) | End graph with a clear user message; `error_code=node_gate_abort`; **not cached** |

Tools emit machine-readable prefixes: `[TOOL_ERROR]`, `[TOOL_EMPTY]`, `[CIRCUIT_OPEN]`.
CRAG document grading remains the *semantic* quality filter; node gates are *structural*
contract checks only (no extra LLM calls).

Prometheus: `rag_node_gate_total{result="quarantine|abort"}`.

## Observability

- **Request IDs** — send or accept `X-Request-ID`; echoed on responses and included in logs.
- **JSON logs** — enabled when `ENVIRONMENT=production`.
- **Prometheus** — `GET /metrics` on the API; scrape + store via the `prometheus` compose service.
- **Grafana** — pre-provisioned dashboard **Agentic RAG Overview** (compose service on `:3000`).
- **Idempotency** — optional `Idempotency-Key` on `POST /query` (Redis-backed, 409 on body mismatch).
- **LangSmith** — optional full LangChain/LangGraph traces when `LANGSMITH_TRACING=true`.
- **Node gates** — quarantine/abort counters on `/metrics` (`rag_node_gate_total`).

### Prometheus + Grafana (local feel)

With the API already running on port 8000 (Docker or local uvicorn):

```bash
docker compose up prometheus grafana -d
```

Then open:

| URL | What |
|-----|------|
| http://localhost:9090 | Prometheus UI (raw queries / targets) |
| http://localhost:3000 | Grafana — login `admin` / `admin` |

In Grafana: **Dashboards → Agentic RAG → Agentic RAG Overview**.

Ask a few questions in the app so lines appear (refresh is 10s). Change the default password after first login.

## Scaling

For production scale, in rough order of effort:

1. **docker-compose defaults** — Redis + Chroma HTTP server + API + nginx frontend (API key injected server-side). Set `CHROMA_MODE=http`, `RATE_LIMIT_BACKEND=redis`.
2. **Multiple API workers** — safe with Redis-backed rate limits / cost budgets (`RATE_LIMIT_BACKEND=redis`) and Chroma HTTP (not local SQLite).
3. **Redis response cache** (above) — cut repeat-query LLM cost/latency; flushed on re-ingest.
4. **Load balancing** — nginx or a cloud load balancer; set `TRUST_PROXY_HEADERS=true` and `TRUSTED_HOSTS=...` when terminating TLS upstream.
5. **Auto-scaling** — Kubernetes or ECS, using `/health` for liveness and `/health/ready` for readiness probes (checks Chroma, OpenAI key, Redis, extra sources, optional Groq/NVIDIA/Supabase). `/health/ready` is auth-gated by default: either give the probe the `X-API-Key` header or set `PROTECT_READINESS_ENDPOINT=false` when the probe cannot send headers and the network already restricts access.

Set `MAX_CONCURRENT_QUERIES` per replica against your provider's concurrency limit, and
size replicas so `total_replicas × MAX_CONCURRENT_QUERIES` stays under it. Verify with a
load test before trusting the numbers:

```bash
pip install -r requirements-load.txt
locust -f tests/load/locustfile.py --host http://staging:8000 --headless -u 50 -r 10 -t 5m
```

Beyond a single host, the known ceiling is BM25: `src/retrieval/retriever.py` builds the
sparse index in-process, so every worker holds the whole corpus in memory and rebuilds it
whenever the document count changes. That is fine at the current corpus size; past it,
move to a store with native hybrid search (Qdrant, Weaviate, or pgvector + `tsvector`).

## Troubleshooting

### Server won't start in production

```
RuntimeError: Unsafe production configuration: API_KEY must be set — authentication is mandatory in production
```

This is intentional — set `API_KEY` (and `OPENAI_API_KEY`) before setting
`ENVIRONMENT=production`. See the Security Checklist above.

### Query times out (504)

- Check `OPENAI_API_KEY` is valid and has available quota
- Check `REQUEST_TIMEOUT_SECONDS` (client-facing) vs `OPENAI_TIMEOUT_SECONDS` (per-LLM-call) — both must be long enough for your slowest mode (`multi_hop`/`decompose` make several sequential LLM calls)

### Rate limited unexpectedly (429)

- Check `MAX_QUERIES_PER_MINUTE_PER_CLIENT` — one API key or IP shares one bucket
- Check `MAX_TOKENS_PER_MINUTE`/`MAX_TOKENS_PER_HOUR` — this is a process-wide budget shared by *all* clients

### Low quality answers

- Run `python -m src.evaluation.evaluate_all_modes` to diagnose which mode/metric is weak
- Increase `RETRIEVAL_TOP_K`
- Lower `GRADER_RELEVANCE_THRESHOLD` (less strict filtering) or raise it (stricter — more retries/fallbacks)
- Re-ingest the knowledge base if the corpus is outdated

### High costs

- Check the per-query cost logs (`Token usage | ... | cost=$...`) to find expensive queries
- Prefer `router`, `crag`, or `tools` modes over `decompose`/`multi_hop`/`agentic` for latency- and cost-sensitive traffic (fewer LLM calls)
- Lower `MAX_OUTPUT_TOKENS` if answers are longer than needed

---

See the root [README.md](../README.md) for full project context and [GUARDRAILS.md](GUARDRAILS.md) / [PRIVACY_COMPLIANCE.md](PRIVACY_COMPLIANCE.md) for the safety layers enforced on every request.
