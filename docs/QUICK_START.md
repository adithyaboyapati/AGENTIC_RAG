# Quick Start Guide — Agentic RAG

Get up and running with the complete multi-mode Agentic RAG system in 5 minutes.

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
#   - QUALITY_GUARDRAILS_ENABLED: enable extra LLM quality checks
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

Opens http://localhost:5173 with mode selector, chat, agent traces, and memory controls.
Details: [frontend/README.md](../frontend/README.md).

### Option B: Streamlit App

```bash
streamlit run streamlit_app.py
```

Opens http://localhost:8501 with the same modes and traces.

### Option C: CLI

```bash
# List available modes
python -m src.cli --help

# Query any mode with verbose output
python -m src.cli ask "What is Self-RAG?" --mode crag -v

# Modes available:
#  - baseline: Plain retrieve → generate
#  - router: Intent-aware routing
#  - crag: Corrective RAG with grading loop
#  - decompose: Break query into sub-questions
#  - multi_hop: Sequential retrieval with reflection
#  - tools: Tool-augmented agent (retrieve, web, calculator)
#  - agentic: Unified orchestrator (picks best strategy)
#  - consensus: Multi-agent debate (Proposer + Critic + Consensus Judge)
```

### Option D: REST API

```bash
# Start server
python -m uvicorn src.api.server:app --reload --port 8000

# Sync query (full JSON when complete)
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is Self-RAG?",
    "mode": "crag"
  }' | jq

# Streaming query (SSE: steps + answer tokens as they arrive)
# The React frontend uses this endpoint by default.
curl -N http://localhost:8000/query/stream \
  -H "Content-Type: application/json" \
  -d '{"question": "What is Self-RAG?", "mode": "agentic"}'

# Check modes (requires X-API-Key header if REQUIRE_API_KEY=true)
curl http://localhost:8000/modes

# Liveness (always unauthenticated)
curl http://localhost:8000/health

# Readiness — checks Chroma, OpenAI config, Redis, optional deps
curl http://localhost:8000/health/ready

# Prometheus metrics (scraped by monitoring/prometheus.yml)
curl http://localhost:8000/metrics
```

> By default (`REQUIRE_API_KEY=false` in `.env.example`), no key is needed locally. Once
> `ENVIRONMENT=production`, the server requires `API_KEY` and refuses to start without it
> — see [PRODUCTION.md](PRODUCTION.md). Requests are also rate-limited per client
> (`MAX_QUERIES_PER_MINUTE_PER_CLIENT`) — see [GUARDRAILS.md](GUARDRAILS.md).

---

## Example Queries

Try these to see each mode's strengths:

### 1. **Simple Conceptual** (Baseline works well)
```bash
python -m src.cli ask "What is retrieval-augmented generation?" --mode baseline -v
python -m src.cli ask "What is retrieval-augmented generation?" --mode crag -v
```
Compare: Baseline is faster, CRAG is more thorough.

### 2. **Comparison** (Decompose excels)
```bash
python -m src.cli ask "Compare naive RAG and advanced RAG" --mode decompose -v
```
Watch: Query broken into sub-questions, retrieved in parallel.

### 3. **Multi-Part Question** (Multi-hop chains them)
```bash
python -m src.cli ask "What fallback does CRAG use when retrieval fails?" --mode multi_hop -v
```
Watch: Sequential hops with reflection after each step.

### 4. **Diverse Needs** (Tools mode)
```bash
python -m src.cli ask "What is 12 * 34 and what is Self-RAG?" --mode tools -v
```
Watch: Agent selects retrieval for Self-RAG, calculator for math.

### 5. **Adaptive Strategy** (Agentic mode)
```bash
python -m src.cli ask "Compare RAG vs Agentic RAG and explain Self-RAG grading" --mode agentic -v
```
Watch: System analyzes complexity and picks optimal strategy.

---

## Evaluate System Quality

```bash
# Offline golden-set gate (no API calls — also runs in CI)
python -m src.evaluation.retrieval_metrics --offline

# Retrieval metrics vs data/eval/golden_qa.json (needs ingested corpus)
python -m src.evaluation.retrieval_metrics

# Run comprehensive RAGAS-inspired evaluation across all modes
python -m src.evaluation.evaluate_all_modes

# View results
cat ragas_eval_results.json | jq '.' | less

# Summary by mode
python -c "
import json
data = json.load(open('ragas_eval_results.json'))
modes = {}
for r in data:
    if r['mode'] not in modes: modes[r['mode']] = []
    modes[r['mode']].append(r)
    
for mode in sorted(modes.keys()):
    evals = modes[mode]
    avg_overall = sum(e['overall_score'] for e in evals) / len(evals)
    print(f'{mode:12} → {avg_overall:.3f}')
"
```

---

## Project Structure

```
Agentic_RAG/
├── frontend/                    # React + Vite chat UI (primary)
├── monitoring/                  # Prometheus + Grafana provisioning
├── src/
│   ├── config.py                 # env-driven settings
│   ├── llm.py                    # OpenAI primary + optional Groq fallback
│   ├── schemas.py                # AgentResponse, Citation
│   ├── prompts.py                # ChatPromptTemplate library
│   ├── guardrails.py / privacy.py
│   ├── runner.py                 # Dispatch: guardrails, cache, memory, modes
│   ├── streaming.py              # SSE step/token emitter
│   ├── cache/redis_cache.py      # Answer cache + idempotency
│   ├── resilience/circuit_breaker.py
│   ├── ingestion/                # cleanse, chunking, parent_store, ingest
│   ├── retrieval/                # hybrid/MMR, reranker, citations
│   ├── memory/                   # compact packing + optional Supabase
│   ├── agents/                   # router, grader, followups, …
│   ├── graph/                    # LangGraph per mode
│   ├── tools/                    # retrieve_docs, web_search, calculator
│   ├── rag/baseline.py
│   ├── api/
│   │   ├── server.py             # /query, /query/stream, /health*, /metrics
│   │   ├── rate_limit.py         # Redis or memory sliding window
│   │   ├── metrics.py            # Prometheus instrumentation
│   │   ├── security.py / health.py
│   └── evaluation/
│       ├── metrics.py            # RAGAS-inspired LLM-as-judge
│       ├── retrieval_metrics.py  # Golden-set hit/recall/MRR
│       └── evaluate_all_modes.py
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
└── docs/                         # CONCEPTS, ROADMAP, PRODUCTION, …
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

## Understanding the Modes

### 1️⃣ **Baseline RAG** (Phase 1)
- Fixed pipeline: retrieve → generate
- Fastest, simplest, lowest quality
- **Use for**: Quick answers, high-volume queries

### 2️⃣ **Router** (Phase 2)
- Analyzes intent: direct → retrieve → web
- Decides whether to retrieve at all
- **Use for**: Multi-intent systems

### 3️⃣ **CRAG** (Phase 3) ⭐ **Best Quality**
- Grades each retrieved document
- Rewrites query if grades are low
- Retries or falls back to web
- **Use for**: Quality-critical applications

### 4️⃣ **Decompose** (Phase 4)
- Breaks complex questions into sub-queries
- Retrieves in parallel
- Synthesizes results
- **Use for**: Comparative questions, multi-part requirements

### 5️⃣ **Multi-Hop** (Phase 5)
- Sequential retrieval with reflection
- Each hop depends on previous answer
- Agent decides when to stop
- **Use for**: Chain-of-reasoning questions

### 6️⃣ **Tools** (Phase 6)
- Dynamic tool selection (retrieve, web, calculator)
- LLM picks best tool per sub-task
- Extensible to any tool
- **Use for**: Diverse information needs

### 7️⃣ **Agentic** (Phase 7)
- Unified orchestrator analyzing question
- Picks best strategy automatically
- Combines all patterns
- **Use for**: Production systems

---

## Key Concepts

### LangChain
- **Prompts** (`ChatPromptTemplate`) — templated instructions
- **Chains** (LCEL) — composable components
- **Tools** (`@tool`) — callable functions for agents
- **Structured Output** (Pydantic) — typed LLM responses

### LangGraph
- **StateGraph** — defines nodes and edges
- **Nodes** — functions that process state
- **Edges** — conditions determining next node
- **Send** — parallel execution in maps
- **Loops** — retry logic, reflection cycles

### Vector DB
- **ChromaDB** — embedded vector database
- **Embeddings** — OpenAI text-embedding-3-small
- **Retriever** — k-NN search with similarity

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

### "Tools mode is slow / returning 0s"
- Tools mode requires tool output validation
- Try: `python -m src.cli ask "What is RAG?" --mode tools -v`

---

## Next Steps

1. **Try all modes** with the example queries above
2. **Run evaluation** to see quality differences
3. **Read `docs/CONCEPTS.md`** for learning details
4. **Deploy via Docker** for production use
5. **Customize prompts** in `src/prompts.py` for your domain

---

## Additional Resources

- **Learning Path**: [ROADMAP.md](ROADMAP.md) (phases 0–9, all complete)
- **Architecture**: [LANGCHAIN_STACK.md](LANGCHAIN_STACK.md)
- **Production Deployment**: [PRODUCTION.md](PRODUCTION.md) (Docker, Redis cache, Prometheus/Grafana)
- **Guardrails & Rate Limiting**: [GUARDRAILS.md](GUARDRAILS.md)
- **Privacy & PII/PHI**: [PRIVACY_COMPLIANCE.md](PRIVACY_COMPLIANCE.md)
- **Observability**: [LANGSMITH_TRACING.md](LANGSMITH_TRACING.md)
- **Concepts & Theory**: [CONCEPTS.md](CONCEPTS.md)
- **Frontend**: [../frontend/README.md](../frontend/README.md)
- **Historical build reports**: `docs/archive/` (point-in-time snapshots, not maintained)
