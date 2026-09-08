# Agentic RAG

<p align="center">
  <img src="frontend/src/assets/hero.png" alt="Agentic RAG" width="160" />
</p>

<p align="center">
  <strong>Canonical Agentic RAG</strong> — unified LangGraph pipeline with evidence, verification, and citations<br/>
  with citations, guardrails, and the hardening needed to run it beyond a notebook.
</p>

<p align="center">
  <a href="https://github.com/adithyaboyapati/AGENTIC_RAG/actions/workflows/ci.yml"><img src="https://github.com/adithyaboyapati/AGENTIC_RAG/actions/workflows/ci.yml/badge.svg?branch=dev" alt="CI" /></a>
  <img src="https://img.shields.io/badge/python-3.10-blue.svg" alt="Python 3.10" />
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License" />
  <img src="https://img.shields.io/badge/LangGraph-orchestrated-purple.svg" alt="LangGraph" />
</p>

A question hits the **canonical Agentic RAG pipeline**: automatic routing, strategy selection, federated retrieval, evidence grading, verification, and citations. Retrieval is not PDF-only: matching hits from a SQLite research catalog, a sample ops API, and a lab MCP server are cited next to the corpus chunks. Every answer runs through the same injection, PII/PHI, and rate/cost controls whether you use the React UI, CLI, Streamlit, or FastAPI.

```
User Question
     │
     ▼
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│ Query Router│────▶│ Strategy Picker  │────▶│  Retriever  │
└─────────────┘     │ (decompose /     │     └──────┬──────┘
     │               │  multi-hop /     │            │
     │ direct answer │  simple / auto)  │            ▼
     ▼               └──────────────────┘     ┌─────────────┐
┌─────────────┐                               │  Evidence   │─── rewrite / retry
│  LLM Answer │                               └──────┬──────┘
└─────────────┘                                      │ verified
                                                      ▼
                                               ┌─────────────┐
                                               │ Verification│
                                               └─────────────┘
```

**Try it:** [Quick start](#quick-start) · [Architecture](#agent-modes) · [Docs](#documentation)

---

## Why this exists

Most RAG demos are a single retrieve → generate chain. This repo is a **learning system that grew into a production-shaped service**: a single canonical Agentic RAG graph, hybrid retrieval, and the operational controls (auth, budgets, caches, continuous evaluation) that keep an LLM from becoming an unbounded bill.

| Traditional RAG | This project |
|-----------------|--------------|
| Always retrieve → generate | Canonical graph decides route, strategy, and retries |
| One pass, no retry | Evidence grading, rewrite, and web fallback |
| One corpus (PDFs) | PDFs plus SQLite catalog, sample ops API, and lab MCP |
| One query in | Internal decompose / multi-hop strategies |
| One generator | Verification + citation provenance on every answer |
| Notebook-only | FastAPI + React, Docker Compose, Prometheus |

Concepts: [docs/CONCEPTS.md](docs/CONCEPTS.md). Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Migration history: [docs/ROADMAP.md](docs/ROADMAP.md).

---

## Agent modes

Production uses a **single canonical pipeline** (`canonical_pipeline_version = v1`).

| Client mode | Status | Behavior |
|-------------|--------|----------|
| `canonical` | **Preferred** | Full canonical graph with automatic strategy selection |
| `agentic`, `baseline`, `router`, `crag`, `decompose`, `multi_hop`, `tools`, `consensus` | Deprecated | Accepted for backward compatibility; mapped internally to canonical strategies; emits deprecation metrics |

The UI exposes one production mode. Clients should use `POST /query` or `POST /query/stream` and consume **answer**, **citations**, **verification**, and **response_status** — not graph implementation details.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/LEGACY_RETIREMENT_INVENTORY.md](docs/LEGACY_RETIREMENT_INVENTORY.md).

---

## Quick start

**You need:** Python 3.10, Node.js 20+ (for the UI), and an `OPENAI_API_KEY`. Optional: NVIDIA rerank key, Groq fallback, Redis.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # set OPENAI_API_KEY; never commit .env
python -m src.ingestion.ingest --source data/sample_docs
```

**React UI (recommended)** — API in one terminal, UI in another:

```bash
uvicorn src.api.server:app --reload --port 8000
cd frontend && npm install && npm run dev
# http://localhost:5173
```

**CLI / API / Streamlit**

```bash
python -m src.cli ask "What is corrective RAG?" --mode canonical -v

curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is Self-RAG?", "mode": "canonical"}'

streamlit run streamlit_app.py     # http://localhost:8501
```

Example questions per mode: [docs/QUICK_START.md](docs/QUICK_START.md). Frontend env: [frontend/README.md](frontend/README.md).

```bash
ruff check src/ tests/ streamlit_app.py
pytest -q
```

---

## What else is in the box

**Retrieval** — Hybrid dense + BM25 (RRF) or MMR; NVIDIA or FlashRank rerank; parent-child sections; table/figure chunks; sentence-level context compression. Extra sources (SQLite papers/benchmarks, `/kb` ops catalog, lab MCP) federate into `retrieve()` when they match.

**Safety** — Jailbreak/injection scans (direct + indirect, including retrieved chunks), PII/PHI redact-or-block, AST-only calculator (no `eval()`), webhook SSRF and ingest-path allowlists, production boot that refuses missing keys, short `API_KEY`, `CORS_ORIGINS=*`, or client-asserted RBAC.

**Serving** — SSE streaming (`POST /query/stream`), per-client rate limits, token budgets, concurrency ceiling (`503 Retry-After`), Redis exact + semantic cache, Groq chat fallback, circuit breakers on rerank and web search.

**Ops** — Docker Compose (API + Redis + Chroma + frontend; Prometheus/Grafana optional), `/health` + `/health/ready` + `/metrics`, LangSmith tracing, golden-set retrieval gate in CI.

**Feedback loop** — Thumbs up/down + failure tags + free-text comment on every answer (`POST /feedback`), PII-redacted and stored in Supabase (`answer_feedback`, SQLite fallback in dev). `GET /feedback/summary` gives negative-rate per mode and top failure categories; `rag_feedback_total{mode,rating}` is scraped by Prometheus; `python -m src.feedback.export` turns thumbs-down into golden-set candidates for the eval gate.

Full list and deploy notes: [docs/PRODUCTION.md](docs/PRODUCTION.md) · [docs/GUARDRAILS.md](docs/GUARDRAILS.md) · [docs/PRIVACY_COMPLIANCE.md](docs/PRIVACY_COMPLIANCE.md).

---

## Repository map

```
frontend/          React + Vite chat (SSE, citations, pipeline debug)
src/graph/         Canonical graph v1 (+ shared nodes, evidence, verification)
src/contracts/     Canonical state, evidence, verification, API response
src/retrieval/     Hybrid retrieve, rerank, compression, citations, federation
src/sources/       SQLite catalog, sample ops API (/kb), lab MCP
src/ingestion/     Cleanse, parent-child chunk, document registry, job queue
src/evaluation/    Shadow, canary, continuous eval, regression gates
src/api/           FastAPI: /query, /query/stream, /ops/*, /feedback, /metrics
src/security/      Prompt-injection detector
src/cache/         Redis exact cache + semantic cache (pipeline-version keyed)
monitoring/        Prometheus + Grafana provisioning
data/sample_docs/  Sample corpus (rag.pdf)
docs/              Architecture, API, evaluation, deployment (see DOCUMENTATION_MAP.md)
```

---

## Documentation

| Doc | For |
|-----|-----|
| [docs/DOCUMENTATION_MAP.md](docs/DOCUMENTATION_MAP.md) | **Start here** — authoritative doc index |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Current production architecture |
| [docs/BACKEND_END_TO_END_GUIDE.pdf](docs/BACKEND_END_TO_END_GUIDE.pdf) | Printable end-to-end system reference |
| [docs/LANGGRAPH.md](docs/LANGGRAPH.md) | Canonical graph nodes & state |
| [docs/API.md](docs/API.md) | HTTP routes and schemas |
| [docs/EVALUATION.md](docs/EVALUATION.md) | Metrics, shadow/canary, continuous eval |
| [docs/QUICK_START.md](docs/QUICK_START.md) | Example queries and troubleshooting |
| [docs/CONCEPTS.md](docs/CONCEPTS.md) | RAG vs agentic RAG concepts |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Historical phase-by-phase build |
| [docs/LANGCHAIN_STACK.md](docs/LANGCHAIN_STACK.md) | Module map |
| [docs/PRODUCTION.md](docs/PRODUCTION.md) | Docker, cache, scaling |
| [docs/GUARDRAILS.md](docs/GUARDRAILS.md) | Injection, rate limits, quality |
| [docs/PRIVACY_COMPLIANCE.md](docs/PRIVACY_COMPLIANCE.md) | PII/PHI policy |
| [docs/LANGSMITH_TRACING.md](docs/LANGSMITH_TRACING.md) | Tracing |
| [AGENTIC_RAG_DEEP_DIVE.md](AGENTIC_RAG_DEEP_DIVE.md) | **Historical** pre-canonical deep dive |
| [LANGGRAPH_DEEP_DIVE.md](LANGGRAPH_DEEP_DIVE.md) | **Historical** seven-graph reference |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Pins, tests, PR loop |
| [SECURITY.md](SECURITY.md) | Vulnerability reporting |

---

## Development

Default branch is **`dev`**. Promote to **`prod`** with a PR after CI is green.

```bash
pytest -q --cov=src --cov-fail-under=60
python -m src.evaluation.retrieval_metrics --offline   # CI golden set
python -m src.evaluation.eval_gates                    # CI regression gates
python -m src.evaluation.retrieval_metrics --gate      # live retrieval gate
python -m src.evaluation.continuous_eval_cli           # scheduled continuous eval
```

CI (`.github/workflows/ci.yml`) runs lint, pytest, the golden-set gate, a frontend production build, and a Docker build that fails if a `.env` is baked into the image.

---

## License

[MIT](LICENSE) © 2026 Adithya Boyapati

Do not commit `.env`. Copy `.env.example`, add your own keys, and keep secrets out of git.
