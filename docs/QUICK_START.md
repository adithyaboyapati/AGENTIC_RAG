# Quick Start Guide — Agentic RAG

Get up and running with the **canonical Agentic RAG** pipeline in 5 minutes.

**Current architecture:** [ARCHITECTURE.md](./ARCHITECTURE.md) · [LANGGRAPH.md](./LANGGRAPH.md) · [DOCUMENTATION_MAP.md](./DOCUMENTATION_MAP.md)

---

## Installation

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up environment
cp .env.example .env
# Edit .env with:
#   - OPENAI_API_KEY (required)
#   - NVIDIA_API_KEY (recommended for reranking — from https://build.nvidia.com)
#   - GROQ_API_KEY (optional — auto-fallback when OpenAI rate-limits / fails)

# 3. Optional: configure ingestion / retrieval / rerank / cache / guardrails
# Edit .env to adjust:
#   - CHUNKING_STRATEGY: section_parent_child (default) or fixed
#   - CLEANSE_ENABLED: true (removes headers/footers) or false
#   - RETRIEVAL_SEARCH_TYPE: hybrid (default), similarity, or mmr
#   - RERANK_PROVIDER: nvidia (default) or flashrank (local)
#   - RERANK_MODEL: nvidia/llama-nemotron-rerank-vl-1b-v2
#   - CACHE_ENABLED / REDIS_URL: answer cache (needs Redis running)
#   - RATE_LIMIT_BACKEND: auto | redis | memory
#   - MULTI_SOURCE_ENABLED: federate SQLite / ops API / lab MCP into retrieve()
#   - EXTRA_SOURCES: database,api,mcp
# See src/config.py for all options

# 4. Ingest documents (already done with rag.pdf)
python -m src.ingestion.ingest --source data/sample_docs
```

---

## Run the System

### Option A: React Frontend (Recommended)

```bash
# Terminal 1 — API
uvicorn src.api.server:app --reload --port 8000

# Terminal 2 — UI
cd frontend && npm install && npm run dev
```

Opens http://localhost:5173 with chat, pipeline debug, citations, and document upload.
Details: [frontend/README.md](../frontend/README.md).

### Option B: Streamlit App

```bash
streamlit run streamlit_app.py
```

Opens http://localhost:8501 with the same canonical pipeline and traces.

### Option C: CLI

```bash
# List available modes
python -m src.cli --help

# Query with verbose pipeline output (preferred mode)
python -m src.cli ask "What is Self-RAG?" --mode canonical -v
```

**Production mode:** `canonical` — one LangGraph workflow with strategy selection, retrieval loops, verification, and citations.

**Deprecated mode strings** (`baseline`, `router`, `crag`, `decompose`, `multi_hop`, `tools`, `agentic`, `consensus`) are still accepted for backward compatibility. They map to canonical strategies internally and emit deprecation metrics. Prefer `canonical` for new integrations.

### Option D: REST API

```bash
# Start server
python -m uvicorn src.api.server:app --reload --port 8000

# Sync query (full JSON when complete)
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is Self-RAG?",
    "mode": "canonical"
  }' | jq

# Streaming query (SSE: steps + answer tokens as they arrive)
curl -N http://localhost:8000/query/stream \
  -H "Content-Type: application/json" \
  -d '{"question": "What is Self-RAG?", "mode": "canonical"}'

# Check modes (requires X-API-Key header if REQUIRE_API_KEY=true)
curl http://localhost:8000/modes

# Liveness (always unauthenticated)
curl http://localhost:8000/health

# Readiness — checks Chroma, OpenAI config, Redis, extra sources, optional deps
curl http://localhost:8000/health/ready

# Sample ops catalog + lab MCP (demo knowledge, not the PDF corpus)
curl 'http://localhost:8000/kb/v1/search?q=retriever-prod'
curl -X POST http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# Prometheus metrics (scraped by monitoring/prometheus.yml)
curl http://localhost:8000/metrics
```

> By default (`REQUIRE_API_KEY=false` in `.env.example`), no key is needed locally. Once
> `ENVIRONMENT=production`, the server requires `API_KEY` and refuses to start without it
> — see [PRODUCTION.md](PRODUCTION.md). Requests are also rate-limited per client
> (`MAX_QUERIES_PER_MINUTE_PER_CLIENT`) — see [GUARDRAILS.md](GUARDRAILS.md).

---

## Example Queries

Try these with `--mode canonical -v` to watch strategy selection, retrieval, and verification:

### 1. Simple conceptual
```bash
python -m src.cli ask "What is retrieval-augmented generation?" --mode canonical -v
```

### 2. Comparison (strategy may select decompose-style retrieval)
```bash
python -m src.cli ask "Compare naive RAG and advanced RAG" --mode canonical -v
```

### 3. Corrective retrieval (grading + rewrite loop)
```bash
python -m src.cli ask "What fallback does CRAG use when retrieval fails?" --mode canonical -v
```

### 4. Multi-part / tool-assisted
```bash
python -m src.cli ask "What is 12 * 34 and what is Self-RAG?" --mode canonical -v
python -m src.cli ask "Who owns retriever-prod and what did experiment 42 conclude about chunking?" --mode canonical -v
```

### 5. Complex synthesis
```bash
python -m src.cli ask "Compare RAG vs Agentic RAG and explain Self-RAG grading" --mode canonical -v
```

---

## Evaluate System Quality

```bash
# Offline golden-set gate (no API calls — also runs in CI)
python -m src.evaluation.retrieval_metrics --offline

# Retrieval metrics vs data/eval/golden_qa.json (needs ingested corpus)
python -m src.evaluation.retrieval_metrics

# CI regression gates (Phase 8)
python -m src.evaluation.eval_gates

# Scheduled continuous evaluation loop
python -m src.evaluation.continuous_eval_cli

# Optional: RAGAS-inspired LLM-judge (deprecated mode aliases still run canonical)
python -m src.evaluation.evaluate_all_modes
```

See [EVALUATION.md](./EVALUATION.md) for metrics definitions. Benchmark numbers are **not yet measured** in this guide — run evaluators against your corpus for deployment-specific results.

---

## Project Structure

```
Agentic_RAG/
├── frontend/                    # React + Vite chat UI (primary)
├── monitoring/                  # Prometheus + Grafana provisioning
├── src/
│   ├── config.py                 # env-driven settings
│   ├── llm.py                    # OpenAI primary + optional Groq fallback
│   ├── contracts/                # CanonicalAgentState, evidence, verification
│   ├── prompts.py                # ChatPromptTemplate library
│   ├── guardrails.py / privacy.py
│   ├── runner.py                 # Guardrails, cache, memory, canonical dispatch
│   ├── streaming.py              # SSE step/token emitter
│   ├── cache/                    # Redis exact + semantic cache
│   ├── resilience/circuit_breaker.py
│   ├── ingestion/                # cleanse, chunking, parent_store, ingest
│   ├── retrieval/                # hybrid/MMR, rerank, citations, federation
│   ├── memory/                   # compact packing + optional Supabase
│   ├── agents/                   # router, grader, decomposer, strategy helpers
│   ├── graph/                    # canonical_graph.py + shared nodes
│   ├── tools/                    # retrieve_docs, query_database, web_search, …
│   ├── sources/                  # SQLite catalog, sample ops API, lab MCP
│   ├── api/
│   │   ├── server.py             # /query, /query/stream, /ops/*, /health*, /metrics
│   │   ├── rate_limit.py         # Redis or memory sliding window
│   │   ├── metrics.py            # Prometheus instrumentation
│   │   └── security.py / health.py
│   └── evaluation/               # shadow, canary, continuous eval, regression gates
├── data/
│   ├── sample_docs/rag.pdf
│   ├── eval/golden_qa.json       # Retrieval golden set (CI offline gate)
│   ├── chroma_db/                # Local Chroma (compose uses HTTP server)
│   └── parent_store.json
├── tests/
├── streamlit_app.py              # Legacy UI
├── docker-compose.yml            # API + Redis + Chroma + frontend (+ Prometheus/Grafana)
├── Dockerfile
├── .github/workflows/ci.yml      # Lint + pytest + golden gate + frontend + Docker
└── docs/                         # See DOCUMENTATION_MAP.md
```

### Full stack with Docker Compose

```bash
cp .env.production.example .env.production
# fill OPENAI_API_KEY, NVIDIA_API_KEY, API_KEY, …

docker compose up -d                 # redis, chroma, API, frontend (:8080)
docker compose up prometheus grafana -d   # optional observability (:9090, :3000)
```

See [PRODUCTION.md](PRODUCTION.md) for ports, cache behavior, and the Grafana dashboard.

---

## Key Concepts

### LangChain
- **Prompts** (`ChatPromptTemplate`) — templated instructions
- **Chains** (LCEL) — composable components
- **Tools** (`@tool`) — callable functions for agents
- **Structured Output** (Pydantic) — typed LLM responses

### LangGraph (canonical graph)
- **StateGraph** — `src/graph/canonical_graph.py`
- **CanonicalAgentState** — typed state with reducers (`src/contracts/state.py`)
- **Nodes** — classify, strategy_select, retrieve, grade, generate, verify, finalize, …
- **Conditional edges** — routing, retry loops, abstention
- **Verification** — always-on before finalize (see [LANGGRAPH.md](./LANGGRAPH.md))

### Vector DB
- **ChromaDB** — embedded or HTTP vector database
- **Embeddings** — OpenAI text-embedding-3-small
- **Hybrid retrieval** — dense + BM25 with RRF fusion

---

## Troubleshooting

### "No documents found"
```bash
python -m src.ingestion.ingest --source data/sample_docs --force
```

### "API key not found"
```bash
export OPENAI_API_KEY="sk-..."
# Or set in .env file
```

### Reranking skipped / falling back to FlashRank
```bash
# Ensure NVIDIA key is set (no space after =) and provider matches
# NVIDIA_API_KEY=nvapi-...
# RERANK_PROVIDER=nvidia
# RERANK_MODEL=nvidia/llama-nemotron-rerank-vl-1b-v2

# Or use local rerank without NVIDIA:
# RERANK_PROVIDER=flashrank
# RERANK_MODEL=ms-marco-MiniLM-L-12-v2

# Disable rerank entirely:
# RERANK_ENABLED=false
```

### "ChromaDB connection error"
```bash
# Clear and reingest
rm -rf data/chroma_db
python -m src.ingestion.ingest --source data/sample_docs
```

---

## Next Steps

1. **Run example queries** with `--mode canonical -v`
2. **Run evaluation** — see [EVALUATION.md](./EVALUATION.md)
3. **Read [CONCEPTS.md](./CONCEPTS.md)** for RAG vs agentic RAG theory
4. **Deploy via Docker** — [PRODUCTION.md](./PRODUCTION.md)
5. **Customize prompts** in `src/prompts.py` for your domain

---

## Historical: eight-mode learning path

The repository was originally built as eight separate LangGraph modes (Phases 1–7). That multi-graph runtime was **retired** in Phase 7; capabilities were consolidated into the canonical graph.

For the phase-by-phase build history and removed file paths, see [ROADMAP.md](./ROADMAP.md) (historical) and [LANGGRAPH_DEEP_DIVE.md](../LANGGRAPH_DEEP_DIVE.md) (historical).

---

## Additional Resources

- **Documentation index**: [DOCUMENTATION_MAP.md](./DOCUMENTATION_MAP.md)
- **Architecture**: [ARCHITECTURE.md](./ARCHITECTURE.md)
- **LangGraph**: [LANGGRAPH.md](./LANGGRAPH.md)
- **API**: [API.md](./API.md)
- **Production Deployment**: [PRODUCTION.md](./PRODUCTION.md)
- **Guardrails & Rate Limiting**: [GUARDRAILS.md](./GUARDRAILS.md)
- **Privacy & PII/PHI**: [PRIVACY_COMPLIANCE.md](./PRIVACY_COMPLIANCE.md)
- **Observability**: [LANGSMITH_TRACING.md](./LANGSMITH_TRACING.md)
- **Frontend**: [../frontend/README.md](../frontend/README.md)
- **Historical snapshots**: `docs/archive/` (point-in-time, not maintained)
