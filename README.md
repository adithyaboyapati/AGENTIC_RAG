# Agentic RAG — Production-Grade Research Assistant

A **multi-mode Agentic RAG system** built on LangChain + LangGraph: eight interchangeable
retrieval strategies behind one API, with guardrails, PII/PHI privacy filtering, persistent
conversation memory, vector semantic caching, multi-tenant RBAC, and the hardening needed to run it in production.

> 📖 **Comprehensive Guides & Deep Dives**:
> - [AGENTIC_RAG_DEEP_DIVE.md](AGENTIC_RAG_DEEP_DIVE.md) — Master reverse engineering & runtime architecture guide.
> - [LANGGRAPH_DEEP_DIVE.md](LANGGRAPH_DEEP_DIVE.md) — Code-level LangGraph state machine, nodes, edges, and loops reference.
> - [docs/CONCEPTS.md](docs/CONCEPTS.md) — Conceptual deep dive: Traditional RAG vs. Agentic RAG.

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

Every response passes through input/output guardrails, prompt injection detection, PII/PHI privacy checks, and
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
| Single generator | **Multi-Agent Consensus** — Proposer, Critic, Judge debate |

See [docs/CONCEPTS.md](docs/CONCEPTS.md) for the full conceptual deep dive.

## Supported Agent Modes

| Mode | What It Does |
|------|---------------|
| `baseline` | Fixed pipeline: always retrieve → generate. No agentic decisions. |
| `router` | Agent routes each question to direct answer, retrieval, or web search. |
| `crag` | Grades retrieved docs, rewrites the query on failure, falls back to web search. |
| `decompose` | Splits complex questions into sub-queries; retrieves in parallel (`Send` API). |
| `multi_hop` | Chains sequential retrievals where each hop builds on the last. |
| `tools` | Agent picks tools via function calling: retrieve docs, web search, or calculate. |
| `agentic` | Full orchestrator: analyzes the question, picks a strategy, grades, generates. |
| `consensus` | Multi-agent debate over retrieved chunks. Abstains when the sources cannot support the question. |

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
│   ├── schemas.py                 # AgentResponse / Citation / RBACContext dataclasses
│   ├── runner.py                  # Unified dispatcher — guardrails, privacy, memory, cache
│   ├── streaming.py               # ContextVar SSE emitter for progressive steps/tokens
│   ├── guardrails.py              # Input/output/cost guardrails, RateLimitError
│   ├── security/injection.py      # Layered jailbreak and prompt injection defense
│   ├── privacy.py                 # PII/PHI detection, redaction, policy
│   ├── prompts.py                 # ChatPromptTemplate library
│   ├── bootstrap.py                # LangSmith init (import before LangChain)
│   ├── observability.py            # LangSmith tracing helpers
│   ├── logging_config.py           # Structured stdout / JSON logging
│   ├── cli.py                      # CLI entry point
│   ├── cache/
│   │   ├── redis_cache.py         # Redis exact cache + RBAC isolation + idempotency
│   │   └── semantic_cache.py      # Vector cosine similarity semantic cache
│   ├── resilience/circuit_breaker.py  # Fail-fast for rerank / web search
│   ├── chains/generation.py        # LCEL chains (rag, direct, synthesis, web)
│   ├── ingestion/
│   │   ├── chunking.py            # Section parent-child chunking
│   │   ├── tables.py              # PyMuPDF structured table to Markdown parser
│   │   ├── multimodal.py          # Figure & visual diagram extractor
│   │   ├── queue.py               # Async background ingestion queue & HMAC webhooks
│   │   └── ingest.py              # Cleanse → chunk → Chroma (+ parent store)
│   ├── retrieval/
│   │   ├── retriever.py           # Hybrid/MMR dense + BM25 + RBAC filters
│   │   ├── compression.py         # Dynamic query-informed sentence-level token compression
│   │   └── citations.py           # Citation parsing & grounding
│   ├── memory/                     # Compact history packing + optional Supabase
│   ├── agents/                     # Structured-output chains (incl. followups)
│   ├── graph/                      # LangGraph StateGraphs (incl. consensus debate)
│   ├── tools/                      # retrieve_docs, web_search, calculator
│   ├── rag/baseline.py             # Phase 1 baseline
│   ├── evaluation/                 # RAGAS-style + golden retrieval metrics
│   └── api/
│       ├── server.py                # /query, /query/stream, /ingest/jobs, /health*, /metrics, /modes
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

## Production Hardening & Enterprise Features

This isn't a demo — the following are enforced automatically:

- **Startup refuses unsafe production config.** With `ENVIRONMENT=production` the server will not boot without `OPENAI_API_KEY`, without an `API_KEY` of at least 32 chars, with `CORS_ORIGINS='*'`, or with `API_WORKERS>1` on in-memory budgets (which would silently multiply every ceiling). Keys are compared with `secrets.compare_digest`.
- **Multi-Tenant Document RBAC** — role-based access filtering at both dense vector and sparse BM25 retrieval layers (`RBACContext`), isolating sensitive tenant data.
- **Semantic Caching & Exact Cache** — exact Redis caching combined with fast in-memory vector semantic caching ($\ge 0.94$ similarity) with strict role segregation.
- **Prompt Injection & Jailbreak Defense** — multi-layered lexical and heuristic detection (`src/security/injection.py`) neutralizing DAN, role-play jailbreaks, delimiter hijacking, and system override attempts.
- **Multimodal Ingestion & Context Compression** — extracts structured PDF tables into Markdown matrices, captures embedded figures, and dynamically prunes redundant tokens (saving 30–50% LLM prompt tokens).
- **Asynchronous Ingestion Worker Queue** — background thread queue (`POST /ingest/jobs`) with real-time polling and HMAC-SHA256 signed webhooks.
- **Multi-Agent Consensus & Adversarial Debate** — 3-agent jury (`--mode consensus`) that proposes, challenges, and judges **against retrieved chunks**. It abstains instead of inventing examples or metrics; a lexical overlap backstop drops leftover ungrounded sentences.
- **Rate limiting** at two layers: a per-client sliding window (`src/api/rate_limit.py`, Redis-backed when available via `RATE_LIMIT_BACKEND=auto|redis`) and a process-wide token/query budget (`src/guardrails.py`).
- **Cost control**: every LLM call carries a hard `timeout`, `max_retries`, and `max_tokens` (`src/llm.py`); actual token usage is tracked per query and checked against per-minute/per-hour budgets before dispatch.
- **LLM fallback** — optional Groq secondary (`GROQ_API_KEY`) retries automatically when OpenAI rate-limits or fails; embeddings stay on OpenAI.
- **Response cache** — optional Redis cache for identical `question`+`mode` (skipped when conversation memory would change the answer); flushed on re-ingest.
- **Circuit breakers** on NVIDIA rerank and web search — fail fast after consecutive errors, recover after a cooldown (`src/resilience/`).
- **Capacity backpressure** — a concurrency ceiling (`MAX_CONCURRENT_QUERIES`) returns a fast `503 Retry-After` instead of letting saturation become an unbounded queue and unbounded concurrent LLM spend. Streaming runs carry a total wall-clock deadline, and client disconnect cooperatively cancels the worker rather than billing to completion.
- **Observability** — `GET /metrics` (Prometheus) including token, estimated-cost, and ingestion metrics, pre-provisioned Grafana dashboard, request IDs, optional LangSmith tracing. Operational endpoints (`/metrics`, `/health/ready`) are auth-gated by default; `/health` stays public for liveness probes.
- **Quality guardrails** (optional): LLM-judged faithfulness, relevance, and context precision checks; can reject or flag low-quality answers in production.
- **Citation tracking** — every answer includes precise source attribution (chunk ID, page, section, snippet, retrieval/rerank score).
- **Cross-encoder reranking** — after hybrid over-fetch, candidates are rescored with NVIDIA `llama-nemotron-rerank-vl-1b-v2` (or local FlashRank).
- **No `eval()`** — the calculator tool uses an AST-restricted arithmetic evaluator so prompt injection can't execute code.
- **Context-aware PII/PHI guardrails** — `off | redact | block` per direction, defaulting to redact. Identifier patterns need a label (`Passport No:`) and cards need a valid Luhn checksum, so chunk IDs and order numbers aren't misread as identity; PHI needs clinical context, so "you can bypass the cache" and "what is diabetes?" survive intact.
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

1. [AGENTIC_RAG_DEEP_DIVE.md](AGENTIC_RAG_DEEP_DIVE.md) — Complete end-to-end reverse engineering & runtime architecture guide
2. [LANGGRAPH_DEEP_DIVE.md](LANGGRAPH_DEEP_DIVE.md) — Deep code-level LangGraph state machines, nodes, edges, and loops manual
3. [docs/CONCEPTS.md](docs/CONCEPTS.md) — Understand RAG vs Agentic RAG
4. [docs/ROADMAP.md](docs/ROADMAP.md) — How each mode was built, phase by phase
5. [docs/LANGCHAIN_STACK.md](docs/LANGCHAIN_STACK.md) — Module-by-module architecture map
6. [docs/QUICK_START.md](docs/QUICK_START.md) — Example queries per mode
7. [docs/GUARDRAILS.md](docs/GUARDRAILS.md) — Safety, prompt injection defense, rate limiting, cost control
8. [docs/PRIVACY_COMPLIANCE.md](docs/PRIVACY_COMPLIANCE.md) — PII/PHI handling
9. [docs/PRODUCTION.md](docs/PRODUCTION.md) — Deployment, Docker, CI/CD, scaling
10. [docs/BACKEND_END_TO_END_GUIDE.pdf](docs/BACKEND_END_TO_END_GUIDE.pdf) — System reference manual (agents + E2E)
11. [docs/LANGSMITH_TRACING.md](docs/LANGSMITH_TRACING.md) — Observability setup
