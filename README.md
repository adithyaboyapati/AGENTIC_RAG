# Agentic RAG — Production-Grade Research Assistant

A **multi-mode Agentic RAG system** built on LangChain + LangGraph: seven interchangeable
retrieval strategies behind one API, with guardrails, PII/PHI privacy filtering, persistent
conversation memory, and the hardening needed to run it in production.

## What It Does

A **Research Assistant** that goes far beyond "retrieve → generate":

```
User Question
     │
     ▼
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│ Query Router│────▶│ Strategy Picker  │────▶│  Retriever  │
└─────────────┘     │ (decompose /     │     └──────┬──────┘
     │               │  multi-hop /     │            │
     │ direct answer │  tools / simple) │            ▼
     ▼               └──────────────────┘     ┌─────────────┐
┌─────────────┐                               │  Grader     │─── retry / rewrite
│  LLM Answer │                               └──────┬──────┘
└─────────────┘                                      │ good
                                                      ▼
                                               ┌─────────────┐
                                               │  Generator  │
                                               └─────────────┘
```

Every response passes through input/output guardrails, PII/PHI privacy checks, and
rate/cost limiting — enforced identically whether you call it via CLI, the React UI,
Streamlit, or the FastAPI server.

## RAG vs Agentic RAG (One-Line Summary)

| Traditional RAG | Agentic RAG |
|-----------------|-------------|
| Fixed pipeline: always retrieve → generate | **Agent decides** what to do at each step |
| One retrieval pass | **Adaptive** — retrieve 0, 1, or N times |
| No self-correction | **Evaluates** its own work and retries |
| Single query in, answer out | **Decomposes** complex queries into sub-tasks |
| Retrieval is the only tool | **Multiple tools** — search, calculator, APIs |

See [docs/CONCEPTS.md](docs/CONCEPTS.md) for the full conceptual deep dive.

## The 7 Modes

| Mode | What It Does |
|------|---------------|
| `baseline` | Fixed pipeline: always retrieve → generate. No agentic decisions. |
| `router` | Agent routes each question to direct answer, retrieval, or web search. |
| `crag` | Grades retrieved docs, rewrites the query on failure, falls back to web search. |
| `decompose` | Splits complex questions into sub-queries; retrieves in parallel. |
| `multi_hop` | Chains sequential retrievals where each hop builds on the last. |
| `tools` | Agent picks tools via function calling: retrieve docs, web search, or calculate. |
| `agentic` | Full orchestrator: analyzes the question, picks a strategy, grades, generates. |

All modes return **detailed citations** (chunk ID, page, section, relevance score) and
**follow-up questions** to guide the user's next queries.

See [docs/ROADMAP.md](docs/ROADMAP.md) for how each mode was built, phase by phase.

## Quick Start

```bash
# 1. Create virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 2. Install pinned dependencies
#    Use the venv, not a conda/system base env — the pins are exact, and mixing
#    them into a shared environment is how the suite becomes uncollectable
#    locally while CI stays green.
pip install -r requirements.txt

#    Contributing? Install the dev tooling and hooks instead:
#    pip install -r requirements-dev.txt && pre-commit install

# 3. Configure environment
cp .env.example .env
# Add your OPENAI_API_KEY

# 4. Ingest sample documents
python -m src.ingestion.ingest --source data/sample_docs

# 5a. React UI (recommended) — start API, then frontend
uvicorn src.api.server:app --reload --port 8000
cd frontend && npm install && npm run dev
# → http://localhost:5173

# 5b. Streamlit UI (legacy)
streamlit run streamlit_app.py
# → http://localhost:8501

# 5c. Or the CLI
python -m src.cli ask "What is corrective RAG?" --mode crag --verbose

# 5d. Or the REST API alone
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is Self-RAG?", "mode": "agentic"}'
```

See [frontend/README.md](frontend/README.md) for frontend env vars and production builds.

See [docs/QUICK_START.md](docs/QUICK_START.md) for example queries per mode and troubleshooting.

### Verify your setup

```bash
ruff check src/ tests/ streamlit_app.py
pytest -q
```

Both must pass. CI runs the same commands plus coverage, dependency/image CVE scans, and
a secret scan — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Project Structure

```
Agentic_RAG/
├── frontend/                    # React + Vite chat UI (SSE streaming, citations, follow-ups)
│   ├── src/                     # Components, API client, styles
│   └── README.md                # Frontend setup & env vars
├── monitoring/                  # Prometheus scrape config + Grafana dashboard provisioning
├── docs/
│   ├── CONCEPTS.md              # RAG vs Agentic RAG deep dive
│   ├── ROADMAP.md               # Phase-by-phase build history
│   ├── LANGCHAIN_STACK.md       # LangChain + LangGraph module map
│   ├── QUICK_START.md           # Setup + example queries per mode
│   ├── PRODUCTION.md            # Deployment, Docker, caching, monitoring, scaling
│   ├── GUARDRAILS.md            # Input/output/rate/cost guardrails
│   ├── PRIVACY_COMPLIANCE.md    # PII/PHI detection, redaction, and policy modes
│   ├── LANGSMITH_TRACING.md     # Observability setup and usage
│   ├── BACKEND_END_TO_END_GUIDE.pdf  # System reference manual (end-to-end + agents)
│   └── archive/                 # Historical point-in-time build reports
├── data/
│   ├── sample_docs/             # PDF corpus (rag.pdf)
│   ├── eval/golden_qa.json      # Offline retrieval golden set (CI gate)
│   ├── chroma_db/               # Local Chroma (auto-created; compose uses HTTP server)
│   ├── parent_store.json        # Parent section expansions (auto-created)
│   └── flashrank_cache/         # Optional local FlashRank model cache
├── src/
│   ├── config.py                 # Settings (env-driven, pydantic-settings)
│   ├── llm.py                    # OpenAI primary + optional Groq fallback
│   ├── schemas.py                 # AgentResponse / Citation dataclasses
│   ├── runner.py                  # Unified dispatcher — guardrails, privacy, memory, cache
│   ├── streaming.py               # ContextVar SSE emitter for progressive steps/tokens
│   ├── guardrails.py              # Input/output/cost guardrails, RateLimitError
│   ├── privacy.py                 # PII/PHI detection, redaction, policy
│   ├── prompts.py                 # ChatPromptTemplate library
│   ├── bootstrap.py                # LangSmith init (import before LangChain)
│   ├── observability.py            # LangSmith tracing helpers
│   ├── logging_config.py           # Structured stdout / JSON logging
│   ├── cli.py                      # CLI entry point
│   ├── cache/redis_cache.py        # Optional Redis answer cache + idempotency
│   ├── resilience/circuit_breaker.py  # Fail-fast for rerank / web search
│   ├── chains/generation.py        # LCEL chains (rag, direct, synthesis, web)
│   ├── ingestion/                  # Cleanse → chunk → Chroma (+ parent store)
│   ├── retrieval/                  # Hybrid/MMR → rerank → citations
│   ├── memory/                     # Compact history packing + optional Supabase
│   ├── agents/                     # Structured-output chains (incl. followups)
│   ├── graph/                      # LangGraph StateGraphs per mode
│   ├── tools/                      # retrieve_docs, web_search, calculator
│   ├── rag/baseline.py             # Phase 1 baseline
│   ├── evaluation/                 # RAGAS-style + golden retrieval metrics
│   └── api/
│       ├── server.py                # /query, /query/stream, /health*, /metrics, /modes
│       ├── security.py              # API key auth (constant-time compare)
│       ├── rate_limit.py            # Per-client limiter (Redis or memory)
│       ├── metrics.py               # Prometheus counters/histograms
│       └── health.py                # Liveness/readiness probes
├── tests/                         # pytest (guardrails, API, cache, retrieval, streaming, …)
├── streamlit_app.py               # Legacy chat UI with agent traces
├── Dockerfile                     # Non-root, layer-cached production image
├── docker-compose.yml             # API + Redis + Chroma + frontend + optional Prometheus/Grafana
├── deploy.sh                      # Single-host deployment script
├── .github/workflows/ci.yml       # Lint + pytest + golden gate + frontend build + Docker
├── requirements.txt
├── .env.example / .env.production.example
└── README.md (this file)
```

## Production Hardening

This isn't a demo — the following are enforced automatically:

- **Startup refuses unsafe production config.** With `ENVIRONMENT=production` the server will not boot without `OPENAI_API_KEY`, without an `API_KEY` of at least 32 chars, with `CORS_ORIGINS='*'`, or with `API_WORKERS>1` on in-memory budgets (which would silently multiply every ceiling). Keys are compared with `secrets.compare_digest`.
- **Rate limiting** at two layers: a per-client sliding window (`src/api/rate_limit.py`, Redis-backed when available via `RATE_LIMIT_BACKEND=auto|redis`) and a process-wide token/query budget (`src/guardrails.py`).
- **Cost control**: every LLM call carries a hard `timeout`, `max_retries`, and `max_tokens` (`src/llm.py`); actual token usage is tracked per query and checked against per-minute/per-hour budgets before dispatch.
- **LLM fallback** — optional Groq secondary (`GROQ_API_KEY`) retries automatically when OpenAI rate-limits or fails; embeddings stay on OpenAI.
- **Response cache** — optional Redis cache for identical `question`+`mode` (skipped when conversation memory would change the answer); flushed on re-ingest.
- **Circuit breakers** on NVIDIA rerank and web search — fail fast after consecutive errors, recover after a cooldown (`src/resilience/`).
- **Capacity backpressure** — a concurrency ceiling (`MAX_CONCURRENT_QUERIES`) returns a fast `503 Retry-After` instead of letting saturation become an unbounded queue and unbounded concurrent LLM spend. Streaming runs carry a total wall-clock deadline, and client disconnect cooperatively cancels the worker rather than billing to completion.
- **Observability** — `GET /metrics` (Prometheus) including token and estimated-cost counters, pre-provisioned Grafana dashboard, request IDs, optional LangSmith tracing. Operational endpoints (`/metrics`, `/health/ready`) are auth-gated by default; `/health` stays public for liveness probes.
- **Quality guardrails** (optional): LLM-judged faithfulness, relevance, and context precision checks; can reject or flag low-quality answers in production.
- **Citation tracking** — every answer includes precise source attribution (chunk ID, page, section, snippet, retrieval/rerank score).
- **Cross-encoder reranking** — after hybrid over-fetch, candidates are rescored with NVIDIA `llama-nemotron-rerank-vl-1b-v2` (or local FlashRank).
- **No `eval()`** — the calculator tool uses an AST-restricted arithmetic evaluator so prompt injection can't execute code.
- **Context-aware PII/PHI guardrails** — `off | redact | block` per direction, defaulting to redact. Identifier patterns need a label (`Passport No:`) and cards need a valid Luhn checksum, so chunk IDs and order numbers aren't misread as identity; PHI needs clinical context, so "you can bypass the cache" and "what is diabetes?" survive intact. An over-eager filter that corrupts correct answers is a worse bug than a missed match, and the test suite covers both directions.
- **Advanced ingestion** — section-aware parent-child chunking; cleansing removes headers/footers/boilerplate; fallback to fixed-size chunks.
- **Hardened image** — multi-stage build with no compiler in the runtime layer, non-root user, secrets excluded via `.dockerignore`. CI fails the build if the image contains a `.env`, runs as root, or still has `gcc`.
- **Hardened compose stack** — only the API and frontend publish host ports; Redis, Chroma, Prometheus, and Grafana stay on the internal network, Redis requires a password, and Grafana has no `admin/admin` fallback.
- **CORS** never combines wildcard origins with credentials (an invalid, insecure combination).
- **Supply-chain checks in CI** — `pip-audit`, `npm audit`, Trivy image scanning, and `gitleaks` over full git history, all with pinned tool versions. Dependabot opens grouped weekly update PRs.
- **Retrieval regression gate** — a nightly workflow ingests the corpus and fails on recall@k / MRR / hit-rate regression, so quality can't silently drift while unit tests stay green.

See [docs/GUARDRAILS.md](docs/GUARDRAILS.md), [docs/PRIVACY_COMPLIANCE.md](docs/PRIVACY_COMPLIANCE.md), and [docs/PRODUCTION.md](docs/PRODUCTION.md) for details.

## Tech Stack

**Core AI**
- **LangGraph** — Agent orchestration (StateGraph with nodes, edges, loops)
- **LangChain** — LCEL chains, `ChatPromptTemplate`, retrievers, `@tool` tools
- **ChromaDB** — Local persistent store or HTTP server (via `langchain-chroma`)
- **OpenAI** — Primary LLM + embeddings (via `langchain-openai`)
- **Groq** (optional) — Chat fallback via `langchain-groq` when OpenAI fails
- **NVIDIA NeMo Retriever** — Cross-encoder reranking (`llama-nemotron-rerank-vl-1b-v2`; optional FlashRank local fallback)

**Serving**
- **FastAPI** — REST API with auth, rate limiting, SSE streaming, Prometheus metrics
- **React + Vite** — Primary chat UI (`frontend/`)
- **Streamlit** — Legacy chat UI with agent traces
- **Redis** (optional) — Answer cache, shared rate limits, idempotency keys
- **Supabase** (optional) — Persistent cross-session conversation memory

**Ops**
- **Prometheus + Grafana** — Request/cache/fallback dashboards (`monitoring/`)
- **PyMuPDF** — PDF ingestion
- **DuckDuckGo** — Web search tool/fallback
- **RAGAS-inspired + golden retrieval metrics** — `src/evaluation/`
- **LangSmith** (optional) — Full tracing — see [docs/LANGSMITH_TRACING.md](docs/LANGSMITH_TRACING.md)

## Development

### Running Tests

```bash
pytest -q

# With the coverage gate CI enforces
pytest -q --cov=src --cov-fail-under=55

# Offline golden-set validation (no embeddings / Chroma) — also runs in CI
python -m src.evaluation.retrieval_metrics --offline

# Live retrieval quality with regression thresholds (nightly workflow uses this)
python -m src.evaluation.retrieval_metrics --gate

# Load test — exercises timeouts, rate limits, and the concurrency ceiling together
locust -f tests/load/locustfile.py --host http://localhost:8000
```

### Linting

```bash
ruff check src/ tests/ streamlit_app.py
```

CI (`.github/workflows/ci.yml`) runs lint, pytest, the golden-set gate, a frontend
production build, and a Docker build that fails if any `.env` file ends up baked into
the image.

### Debugging with Verbose Output

```bash
python -m src.cli ask "YOUR QUESTION" --mode crag --verbose
```

Shows router decision, grader summary, agent steps, and sources.

### Branching

- `dev` — default working branch.
- `prod` — promoted via PR from `dev` once CI passes. Protect this branch on GitHub
  (require PR + passing checks) so nothing reaches it except a reviewed merge.

## Further Reading

1. [docs/CONCEPTS.md](docs/CONCEPTS.md) — Understand RAG vs Agentic RAG
2. [docs/ROADMAP.md](docs/ROADMAP.md) — How each mode was built, phase by phase
3. [docs/LANGCHAIN_STACK.md](docs/LANGCHAIN_STACK.md) — Module-by-module architecture map
4. [docs/QUICK_START.md](docs/QUICK_START.md) — Example queries per mode
5. [docs/GUARDRAILS.md](docs/GUARDRAILS.md) — Safety, rate limiting, cost control
6. [docs/PRIVACY_COMPLIANCE.md](docs/PRIVACY_COMPLIANCE.md) — PII/PHI handling
7. [docs/PRODUCTION.md](docs/PRODUCTION.md) — Deployment, Docker, CI/CD, scaling
8. [docs/BACKEND_END_TO_END_GUIDE.pdf](docs/BACKEND_END_TO_END_GUIDE.pdf) — System reference manual (agents + E2E)
9. [docs/LANGSMITH_TRACING.md](docs/LANGSMITH_TRACING.md) — Observability setup
