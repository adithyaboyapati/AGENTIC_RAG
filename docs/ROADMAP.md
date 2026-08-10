# Learning Roadmap — Phase by Phase

**Status:** Phases 0–9 complete (including Phase 8.5 hardening and Phase 9 production
features: frontend, streaming, cache, metrics, circuit breakers, golden eval).

Each phase has **learning goals**, **what to build**, and **how to verify you understood it**.

## Quick Navigation

| Phase | Status | CLI | UI |
|-------|--------|-----|-----|
| 1 Baseline | ✅ Done | `--mode baseline` | React / Streamlit |
| 2 Router | ✅ Done | `--mode router` | React / Streamlit |
| 3 CRAG | ✅ Done | `--mode crag` | React / Streamlit |
| 4 Decompose | ✅ Done | `--mode decompose` | React / Streamlit |
| 5 Multi-hop | ✅ Done | `--mode multi_hop` | React / Streamlit |
| 6 Tools | ✅ Done | `--mode tools` | React / Streamlit |
| 7 Full Agent | ✅ Done | `--mode agentic` | React / Streamlit |
| 8 Production | ✅ Done | REST API + eval suite | N/A |
| 8.5 Hardening | ✅ Done | N/A (cross-cutting) | N/A |
| 9 Prod features | ✅ Done | Cache, metrics, SSE, golden eval | React (primary) |

---

## Phase 0: Foundation (Day 1) ✅ COMPLETE

### What Was Built
- Project structure with LangChain + LangGraph patterns
- Vector store setup (ChromaDB)
- Document ingestion pipeline (PDF → chunks → vectors)
- Configuration and environment management

### Verification
```bash
python -m src.ingestion.ingest --source data/sample_docs
# Output: Indexed 136 chunks from 21 pages
```

---

## Phase 1: Baseline RAG — The "Before" Picture ✅ COMPLETE

### What Was Built
- `src/rag/baseline.py` — Fixed LangChain pipeline (retrieve → generate)
- No agentic decisions — always retrieves, always generates

### Pattern
```python
rag_chain = RAG_PROMPT | llm | str_parser
answer = rag_chain.invoke({"context": context, "question": question})
```

### Try It
```bash
# Simple Q — works well
python -m src.cli ask "What is retrieval-augmented generation?" --mode baseline -v

# Comparative Q — weak answer (only 1 retrieval pass)
python -m src.cli ask "Compare naive RAG and advanced RAG" --mode baseline -v

# Or use Streamlit UI
streamlit run streamlit_app.py  # select "Phase 1 — Baseline RAG"
```

### Checkpoint
This is the baseline you compare all agentic modes against. Notice how it fails on multi-part questions.

---

## Phase 2: Query Router ✅ COMPLETE

### What Was Built
- `src/agents/router.py` — LangChain structured output (Pydantic) classifier
- `src/graph/router_graph.py` — LangGraph routing with conditional edges
- Routes to: direct answer, vector retrieval, web search

### Pattern
```python
router_chain = ROUTER_PROMPT | llm.with_structured_output(RouteDecision)
decision = router_chain.invoke({"question": question})
# Routes to: direct → answer, retrieve → retriever + generator, web_search → web + generator
```

### Try It
```bash
# Greeting — routed to "direct", no retrieval
python -m src.cli ask "Hello!" --mode router -v

# RAG topic — routed to "retrieve"
python -m src.cli ask "What is Self-RAG?" --mode router -v

# Recent news — routed to "web_search"
python -m src.cli ask "Latest AI news" --mode router -v
```

### Checkpoint
First agentic capability: the agent **decides** whether to retrieve at all.

---

## Phase 3: Corrective RAG (CRAG) ✅ COMPLETE

### What Was Built
- `src/agents/grader.py` — LangChain grader_chain (structured output)
- `src/agents/query_rewriter.py` — LangChain rewrite_chain
- `src/graph/crag_graph.py` — LangGraph loop: retrieve → grade → [generate | rewrite → retry | web fallback]

### Pattern
```python
# Grade each chunk
filtered, grades = grade_documents(question, docs)

# If bad, rewrite and retry
if not filtered and retry_count < max_retries:
    rewritten = rewrite_query(question, search_query)
    # loop back to retrieve
elif not filtered:
    # fallback to web search
```

### Try It
```bash
# Watch the grader + retry loop
python -m src.cli ask "What is corrective RAG?" --mode crag -v

# Out-of-corpus question → web fallback
python -m src.cli ask "What is the capital of Mongolia?" --mode crag -v
```

### Checkpoint
Agent **evaluates** its own retrieval and retries if needed. Biggest quality jump over baseline.

---

## Phase 4: Query Decomposition ✅ COMPLETE

### What Was Built
- `src/agents/decomposer.py` — LangChain decompose_chain (structured output)
- `src/graph/decompose_graph.py` — LangGraph map-reduce using `Send` for parallel retrieval
- Synthesizes results via synthesis_chain

### Pattern
```python
# Decompose question into sub-queries
result = decompose_chain.invoke({"question": question})
sub_queries = result.sub_queries  # known upfront

# Parallel retrieve via LangGraph Send
# Each worker: retrieve → collect
# Reduce: combine all contexts + synthesis_chain
```

### Try It
```bash
# Comparative question → decomposed into 3 sub-queries, retrieved in parallel
python -m src.cli ask "Compare naive RAG, advanced RAG, and modular RAG" --mode decompose -v

# Simple question → stays as 1 sub-query
python -m src.cli ask "What is Self-RAG?" --mode decompose -v
```

### Checkpoint
Agent **breaks apart** complex questions; retrieves in **parallel** (map-reduce).

---

## Phase 5: Multi-Hop Retrieval ✅ COMPLETE

### What Was Built
- `src/agents/multi_hop.py` — LangChain analyze_chain + reflect_chain (structured output)
- `src/graph/multi_hop_graph.py` — LangGraph sequential loop with reflection
- Hops build on each other; agent decides when to stop

### Pattern
```python
# Analyze: plan the first hop + decide if multi-hop is needed
analysis = analyze_chain.invoke({"question": question})

# Hop loop: retrieve → reflect → [synthesize | next_hop]
# Each hop's query depends on previous findings
```

### Try It
```bash
# Sequential hops: Hop 1 "What is CRAG?", Hop 2 "What fallback does it use?"
python -m src.cli ask "What fallback does CRAG use when retrieval fails?" --mode multi_hop -v

# Simple Q: single hop only
python -m src.cli ask "What is naive RAG?" --mode multi_hop -v
```

### Checkpoint
Agent **chains sequential** retrievals (unlike Phase 4's parallel). Next query depends on prior answer.

---

## Phase 6: Tool-Augmented Agent ✅ COMPLETE

### What Was Built
- LangChain `@tool` decorators for multiple tools (retrieve, web, calculator)
- LangGraph agent node with tool-calling capability via `llm.bind_tools()`
- Agent selects which tool to use per sub-task dynamically

### Pattern
```python
@tool
def retrieve_docs(query: str) -> str:
    """Search vector store."""
    
@tool
def web_search(query: str) -> str:
    """DuckDuckGo web search."""
    
@tool
def calculator(expr: str) -> str:
    """Evaluate math expressions."""

# LangGraph agent picks tools dynamically
llm_with_tools = llm.bind_tools([retrieve_docs, web_search, calculator])
```

### Try It
```bash
python -m src.cli ask "What is 12 * 34?" --mode tools              # calculator
python -m src.cli ask "Latest AI breakthroughs" --mode tools        # web
python -m src.cli ask "What is Self-RAG?" --mode tools             # retrieve
```

### Checkpoint
Agent **selects tools** dynamically based on question type, beyond just retrieval.

---

## Phase 7: Full LangGraph Orchestration ✅ COMPLETE

### What Was Built
- `src/graph/agent_graph.py` — unified StateGraph combining all patterns
- Single entry point that decides: route → decompose/multi-hop/tools/simple → grade → generate
- Analyzes question to pick best strategy automatically

### Pattern
```
START → router → [direct | web | retrieve]
                      ↓
         strategy analyzer (choose best approach)
              ↓
    [decompose | multi_hop | tools | simple_retrieve]
              ↓
            grade
              ↓
    [generate | rewrite | web_fallback]
              ↓
           END
```

### Try It
```bash
python -m src.cli ask "Compare RAG vs Agentic RAG; explain Self-RAG grading" --mode agentic -v
```

Compare this with Phase 1 baseline on the same question — you'll see the difference in depth and structure.

### Checkpoint
**Full agentic orchestration** — the system analyzes the question and picks the optimal strategy.

---

## Phase 8: Evaluation & Metrics ✅ COMPLETE

### What Was Built
- **RAGAS-Inspired Metrics** (`src/evaluation/metrics.py`) — LLM-as-judge evaluation
- **Comprehensive Evaluation** (`src/evaluation/evaluate_all_modes.py`) — tests all 7 modes
- **Metrics Computed**:
  - **Faithfulness** — Is answer grounded in context (not hallucinated)?
  - **Answer Relevance** — Does answer address the original question?
  - **Context Precision** — What fraction of retrieved docs are relevant?

### Results Summary
```
Mode         | Avg Latency | Faithfulness | Relevance | Overall
baseline     | 3.7s        | 1.000        | 0.833     | 0.944
router       | 4.9s        | 1.000        | 0.783     | 0.928
crag         | 9.9s        | 0.967        | 1.000     | 0.989 ⭐
decompose    | 12.1s       | 0.833        | 0.967     | 0.933
multi_hop    | 13.9s       | 0.833        | 1.000     | 0.944
tools        | 8.5s        | 0.000        | 1.000     | 0.333
agentic      | 13.6s       | 0.867        | 1.000     | 0.956
```

### Run Evaluation
```bash
# Run comprehensive evaluation across all modes
python -m src.evaluation.evaluate_all_modes

# View detailed results
cat ragas_eval_results.json | jq '.[] | select(.mode=="crag")'
```

### Key Insights
- **Best Quality**: CRAG (0.989 overall)
- **Fastest**: Baseline (3.7s)
- **Speed-Quality Tradeoff**: Use baseline/router for speed, crag/agentic for quality
- **Decompose**: Excels at multi-part comparative questions

---

## Implementation Status

| Phase | Status | Files |
|-------|--------|-------|
| 0 Foundation | ✅ Done | config, ingestion, retrieval |
| 1 Baseline RAG | ✅ Done | `rag/baseline.py` |
| 2 Router | ✅ Done | `agents/router.py`, `graph/router_graph.py` |
| 3 CRAG | ✅ Done | `agents/grader.py`, `graph/crag_graph.py` |
| 4 Decompose | ✅ Done | `agents/decomposer.py`, `graph/decompose_graph.py` |
| 5 Multi-hop | ✅ Done | `agents/multi_hop.py`, `graph/multi_hop_graph.py` |
| 6 Tools | ✅ Done | `tools/all_tools.py`, `graph/tools_graph.py` |
| 7 Full Agent | ✅ Done | `agents/orchestrator.py`, `graph/agent_graph.py` |
| 8 Production | ✅ Done | `api/`, `evaluation/`, `Dockerfile`, CI |
| 8.5 Hardening | ✅ Done | `guardrails.py`, `privacy.py`, `api/security.py`, `api/rate_limit.py` |
| 9 Prod features | ✅ Done | `frontend/`, `cache/`, `resilience/`, `streaming.py`, `monitoring/`, golden eval |
| **Total** | **10/10** | — |

## Phase 8.5: Production Hardening ✅ COMPLETE

A senior-architect review surfaced gaps between "runs correctly" and "safe to expose to
real traffic." What changed, beyond Phase 8's initial API/eval work:

- **Removed `eval()`** from the calculator tool (`src/tools/all_tools.py`) — prompt
  injection could otherwise execute arbitrary Python. Replaced with an AST-restricted
  arithmetic evaluator.
- **Mandatory auth in production** — the server now refuses to start if
  `ENVIRONMENT=production` and no `API_KEY` is configured, instead of logging an error and
  continuing to serve (`src/api/server.py`).
- **Per-client rate limiting** (`src/api/rate_limit.py`) on top of the existing
  process-wide budget — one abusive client can no longer exhaust capacity for everyone.
- **Real token/cost tracking**, wired into every request via LangChain's OpenAI callback,
  checked against a budget *before* dispatch (`src/guardrails.py`, `src/runner.py`).
- **Hard LLM-level timeouts/retries/`max_tokens`** (`src/llm.py`) so a client-side timeout
  doesn't leave an abandoned call still billing OpenAI.
- **Guardrail false-positive fixes** — replaced the input keyword blocklist (which
  rejected "what is a token limit?") with credential-pattern detection; fixed the SSN
  regex to require dashes; PHI no longer blocks informational medical questions by
  default (see [PRIVACY_COMPLIANCE.md](PRIVACY_COMPLIANCE.md)).
- **Non-root, secret-free Docker image** — `.dockerignore` added, CI verifies no `.env`
  ends up inside the built image.
- **Removed the global retrieval lock** that serialized every vector search process-wide,
  which defeated the parallel retrieval the decompose graph is designed for.
- **Pinned dependencies**, added `ruff` lint + Docker build to CI, moved secrets off
  async event-loop-blocking calls in the API layer.

See [GUARDRAILS.md](GUARDRAILS.md), [PRIVACY_COMPLIANCE.md](PRIVACY_COMPLIANCE.md), and
[PRODUCTION.md](PRODUCTION.md) for the details of each.

## Phase 9: Production Features ✅ COMPLETE

After Phase 8, production feedback led to new capabilities:

### Advanced Ingestion & Retrieval
- **Section-aware parent-child chunking** (`src/ingestion/chunking.py`) — PDFs with TOC/headings are split into semantic parents + child chunks, enabling precise retrieval with context expansion
- **PDF cleansing** (`src/ingestion/cleanse.py`) — headers, footers, page numbers, boilerplate, and irrelevant sections (References, Appendices) are removed before indexing
- **Hybrid retrieval** — dense + BM25 fusion with RRF, or MMR, instead of only vector similarity
- **Cross-encoder reranking** (`src/retrieval/reranker.py`) — after over-fetching candidates, rescore with NVIDIA NeMo Retriever (`llama-nemotron-rerank-vl-1b-v2`) or local FlashRank before `top_k` truncation
- **Parent store** — cached parent section expansions for efficient context synthesis
- **Chroma HTTP mode** — `CHROMA_MODE=http` for docker-compose / multi-worker (local SQLite remains the default for single-process dev)

### Citation & Grounding
- **Citation dataclass** (`src/schemas.py::Citation`) — chunk ID, source, page, section, snippet, relevance score
- **Citation extraction** (`src/retrieval/citations.py`) — `build_response()` assembles `AgentResponse` with validated citations and context docs
- **Golden retrieval eval** (`src/evaluation/retrieval_metrics.py` + `data/eval/golden_qa.json`) — hit-rate, recall@k, MRR; `--offline` gate in CI

### Follow-Up Questions
- **Follow-up generation** (`src/agents/followups.py`) — generates 3 grounded follow-up questions post-answer, using fresh retrieval or answer snippets
- **Frontend chips** — React UI renders clickable follow-up suggestions so users can explore related topics

### Streaming & Frontend
- **True SSE streaming** (`src/streaming.py`, `POST /query/stream`) — agent steps as LangGraph nodes finish, answer tokens as they generate
- **Chat UI** (`frontend/`) — React + Vite with markdown, mode selector, citations, traces, memory controls
- **Compose frontend** — nginx image proxies `/api` to the API and injects `API_KEY` server-side

### Resilience & Cost
- **Redis answer cache** (`src/cache/redis_cache.py`) — identical `question`+`mode` hits for `CACHE_TTL_SECONDS`; skipped when memory would change the answer; flushed on re-ingest
- **Redis-backed rate limits** (`RATE_LIMIT_BACKEND=auto|redis|memory`) — shared across API workers
- **Idempotency** — optional `Idempotency-Key` on `POST /query` (Redis-backed)
- **Circuit breakers** (`src/resilience/circuit_breaker.py`) — NVIDIA rerank and web search fail fast after consecutive errors
- **Groq LLM fallback** (`src/llm.py`) — when `GROQ_API_KEY` is set, OpenAI failures (quota/rate limit) retry on Groq; embeddings stay on OpenAI
- **Optional online quality checks** — when `QUALITY_GUARDRAILS_ENABLED=true`, every query is scored for faithfulness, relevance, context precision
- **Fine-grained memory** — compact prompt packing with recent Q+A kept full, older turns kept as questions only

### Observability
- **Prometheus metrics** (`src/api/metrics.py`, `GET /metrics`) — request counts/latency, cache events, LLM fallbacks, rate-limit hits
- **Grafana dashboard** (`monitoring/grafana/`) — pre-provisioned **Agentic RAG Overview**
- **Request IDs** — `X-Request-ID` accepted/propagated on every response

All of these are **optional or env-gated** — local CLI/dev still works with OpenAI + a local Chroma
dir. For production, Redis + Chroma HTTP + frontend + Prometheus/Grafana (see
[PRODUCTION.md](PRODUCTION.md)) are recommended.

---

## Questions to Ask Yourself After Each Phase

1. What decision did the **agent** make that baseline RAG cannot?
2. Where is the **loop** (retry/rethink)?
3. What **state** is passed between steps?
4. How would I **debug** this in production?
5. What **eval** would prove this step improved quality?

---

## Capstone Comparison

Run these questions through **Phase 1 baseline** vs **Phase 5 multi-hop** to see the evolution:

```bash
# Simple Q — baseline works fine
python -m src.cli ask "What is retrieval-augmented generation?" --mode baseline -v
python -m src.cli ask "What is retrieval-augmented generation?" --mode multi_hop -v

# Comparative Q — decompose handles it better than baseline
python -m src.cli ask "Compare naive RAG, advanced RAG, and modular RAG" --mode baseline -v
python -m src.cli ask "Compare naive RAG, advanced RAG, and modular RAG" --mode decompose -v

# Multi-part Q — multi-hop chains the logic
python -m src.cli ask "What fallback does CRAG use when retrieval fails?" --mode baseline -v
python -m src.cli ask "What fallback does CRAG use when retrieval fails?" --mode multi_hop -v
```

Document the difference in depth, reasoning, and structure. That's proof of understanding.
