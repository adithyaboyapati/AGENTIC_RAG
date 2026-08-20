# Agentic RAG

<p align="center">
  <img src="frontend/src/assets/hero.png" alt="Agentic RAG" width="160" />
</p>

<p align="center">
  <strong>Eight retrieval strategies, one API</strong> — LangChain + LangGraph research assistant<br/>
  with citations, guardrails, and the hardening needed to run it beyond a notebook.
</p>

<p align="center">
  <a href="https://github.com/adithyaboyapati/AGENTIC_RAG/actions/workflows/ci.yml"><img src="https://github.com/adithyaboyapati/AGENTIC_RAG/actions/workflows/ci.yml/badge.svg?branch=dev" alt="CI" /></a>
  <img src="https://img.shields.io/badge/python-3.10-blue.svg" alt="Python 3.10" />
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License" />
  <img src="https://img.shields.io/badge/LangGraph-orchestrated-purple.svg" alt="LangGraph" />
</p>

A question hits a **router**, a **strategy picker**, and a **retriever** that can grade, rewrite, and retry. Every answer is cited (chunk, page, section, score) and runs through the same injection, PII/PHI, and rate/cost controls whether you use the React UI, CLI, Streamlit, or FastAPI.

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

**Try it:** [Quick start](#quick-start) · [Modes](#agent-modes) · [Docs](#documentation)

---

## Why this exists

Most RAG demos are a single retrieve → generate chain. This repo is a **learning system that grew into a production-shaped service**: interchangeable agent graphs, hybrid retrieval, and the boring controls (auth, budgets, caches, probes) that keep an LLM from becoming an unbounded bill.

| Traditional RAG | This project |
|-----------------|--------------|
| Always retrieve → generate | Agent decides: retrieve 0, 1, or N times |
| One pass, no retry | CRAG grades chunks, rewrites, falls back to web |
| One query in | Decompose, multi-hop, or tool-calling |
| One generator | Optional **consensus** debate over the same chunks |
| Notebook-only | FastAPI + React, Docker Compose, Prometheus |

Concepts: [docs/CONCEPTS.md](docs/CONCEPTS.md). How each mode was built: [docs/ROADMAP.md](docs/ROADMAP.md).

---

## Agent modes

| Mode | Phase | What it does |
|------|-------|----------------|
| `baseline` | 1 | Fixed retrieve → generate. Fastest baseline. |
| `router` | 2 | Direct answer, retrieval, or web search. |
| `crag` | 3 | Grades docs, rewrites on failure, web fallback. |
| `decompose` | 4 | Splits the question; parallel retrieve (`Send`). |
| `multi_hop` | 5 | Sequential retrieval; each hop uses the last. |
| `tools` | 6 | Function calling: retrieve, web search, calculator. |
| `agentic` | 7 | Orchestrator: pick a strategy, then CRAG-grade. |
| `consensus` | 8 | Proposer → Challenger → Judge **on retrieved chunks**. Abstains when the sources cannot support the question. |

All modes return **citations** and **follow-up questions**. Consensus is stricter on grounding, not a guarantee of span-level faithfulness — details in [docs/GUARDRAILS.md](docs/GUARDRAILS.md).

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
python -m src.cli ask "What is corrective RAG?" --mode crag -v

curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is Self-RAG?", "mode": "agentic"}'

streamlit run streamlit_app.py     # http://localhost:8501
```

Example questions per mode: [docs/QUICK_START.md](docs/QUICK_START.md). Frontend env: [frontend/README.md](frontend/README.md).

```bash
ruff check src/ tests/ streamlit_app.py
pytest -q
```

---

## What else is in the box

**Retrieval** — Hybrid dense + BM25 (RRF) or MMR; NVIDIA or FlashRank rerank; parent-child sections; table/figure chunks; sentence-level context compression.

**Safety** — Jailbreak/injection scans (direct + indirect), PII/PHI redact-or-block, AST-only calculator (no `eval()`), production boot that refuses missing keys, short `API_KEY`, or `CORS_ORIGINS=*`.

**Serving** — SSE streaming (`POST /query/stream`), per-client rate limits, token budgets, concurrency ceiling (`503 Retry-After`), Redis exact + semantic cache, Groq chat fallback, circuit breakers on rerank and web search.

**Ops** — Docker Compose (API + Redis + Chroma + frontend; Prometheus/Grafana optional), `/health` + `/health/ready` + `/metrics`, LangSmith tracing, golden-set retrieval gate in CI.

Full list and deploy notes: [docs/PRODUCTION.md](docs/PRODUCTION.md) · [docs/GUARDRAILS.md](docs/GUARDRAILS.md) · [docs/PRIVACY_COMPLIANCE.md](docs/PRIVACY_COMPLIANCE.md).

---

## Repository map

```
frontend/          React + Vite chat (SSE, citations, traces)
src/graph/         LangGraph modes (baseline → consensus)
src/retrieval/     Hybrid retrieve, rerank, compression, citations
src/ingestion/     Cleanse, parent-child chunk, tables/figures, job queue
src/api/           FastAPI: /query, /query/stream, /ingest/jobs, /health, /metrics
src/security/      Prompt-injection detector
src/cache/         Redis exact cache + in-process semantic cache
monitoring/        Prometheus + Grafana provisioning
data/sample_docs/  Sample corpus (rag.pdf)
docs/              Concepts, roadmap, production, guardrails
```

---

## Documentation

| Doc | For |
|-----|-----|
| [docs/QUICK_START.md](docs/QUICK_START.md) | Per-mode example queries and troubleshooting |
| [docs/CONCEPTS.md](docs/CONCEPTS.md) | RAG vs agentic RAG |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phase-by-phase build |
| [docs/LANGCHAIN_STACK.md](docs/LANGCHAIN_STACK.md) | Module map |
| [docs/PRODUCTION.md](docs/PRODUCTION.md) | Docker, cache, scaling |
| [docs/GUARDRAILS.md](docs/GUARDRAILS.md) | Injection, rate limits, consensus grounding |
| [docs/PRIVACY_COMPLIANCE.md](docs/PRIVACY_COMPLIANCE.md) | PII/PHI policy |
| [docs/LANGSMITH_TRACING.md](docs/LANGSMITH_TRACING.md) | Tracing |
| [AGENTIC_RAG_DEEP_DIVE.md](AGENTIC_RAG_DEEP_DIVE.md) | Runtime architecture |
| [LANGGRAPH_DEEP_DIVE.md](LANGGRAPH_DEEP_DIVE.md) | Graphs, nodes, edges |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Pins, tests, PR loop |
| [SECURITY.md](SECURITY.md) | Vulnerability reporting |

---

## Development

Default branch is **`dev`**. Promote to **`prod`** with a PR after CI is green.

```bash
pytest -q --cov=src --cov-fail-under=55
python -m src.evaluation.retrieval_metrics --offline   # CI golden set
python -m src.evaluation.retrieval_metrics --gate      # live retrieval gate
```

CI (`.github/workflows/ci.yml`) runs lint, pytest, the golden-set gate, a frontend production build, and a Docker build that fails if a `.env` is baked into the image.

---

## License

[MIT](LICENSE) © 2026 Adithya Boyapati

Do not commit `.env`. Copy `.env.example`, add your own keys, and keep secrets out of git.
