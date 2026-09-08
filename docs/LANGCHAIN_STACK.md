# LangChain & LangGraph Stack Conventions

Every AI component in this project uses **LangChain** or **LangGraph**. Everything else
(guardrails, privacy, rate limiting, auth, cache, metrics) is plain Python/FastAPI wrapped
around this core — see [GUARDRAILS.md](GUARDRAILS.md), [PRIVACY_COMPLIANCE.md](PRIVACY_COMPLIANCE.md),
and [PRODUCTION.md](PRODUCTION.md).

## LangChain (building blocks)

| Module | Purpose |
|--------|---------|
| `src/prompts.py` | `ChatPromptTemplate` for all prompts (routing, grading, decomposition, synthesis, follow-ups) |
| `src/llm.py` | OpenAI `ChatOpenAI` primary + optional Groq `ChatGroq` via `with_fallbacks`; shared `timeout` / `max_retries` / `max_tokens` |
| `src/chains/generation.py` | LCEL chains: `prompt \| llm \| StrOutputParser()` |
| `src/agents/router.py` | `router_chain` with structured output |
| `src/agents/grader.py` | `grader_chain` — grades each chunk (Phase 3) |
| `src/agents/query_rewriter.py` | `rewrite_chain` — query rewrite on failed retrieval |
| `src/agents/decomposer.py` | `decompose_chain` — splits complex questions (Phase 4) |
| `src/agents/multi_hop.py` | `analyze_chain`, `reflect_chain` — sequential hops (Phase 5) |
| `src/agents/orchestrator.py` | `choose_strategy` — analyzes question for best pattern (Phase 7) |
| `src/agents/followups.py` | `followup_chain` — generates 3 grounded follow-up questions post-answer |
| `src/retrieval/retriever.py` | Hybrid/MMR/similarity over-fetch → rerank → top_k → optional parent expand + extra-source federation + RBAC filters |
| `src/sources/` | SQLite research catalog, sample ops API (`/kb`), lab MCP (`POST /mcp` + stdio) |
| `src/retrieval/compression.py` | Dynamic query-informed sentence-level token pruning and context compression |
| `src/retrieval/reranker.py` | Cross-encoder rerank: NVIDIA NeMo Retriever API or local FlashRank (`RERANK_PROVIDER`); circuit-breaker wrapped |
| `src/retrieval/citations.py` | Citation/snippet extraction: `docs_to_citations()`, `build_response()` for rich UI/eval payloads |
| `src/tools/all_tools.py` | `@tool` `retrieve_docs`, `query_database`, `query_api`, `query_mcp`, `web_search`, `calculator` (AST-restricted, no `eval()`) |
| `src/ingestion/tables.py` | PyMuPDF structured table detector and Markdown matrix converter |
| `src/ingestion/multimodal.py` | Visual figure and embedded diagram extractor |
| `src/ingestion/queue.py` | Async background ingestion worker queue with progress tracking & HMAC webhooks |
| `src/ingestion/ingest.py` | Document loaders, Chroma (persistent or HTTP); owns embeddings + vector store singletons; orchestrates chunking/cleansing |
| `src/ingestion/chunking.py` | Section-parent-child chunking (TOC/regex parents → recursive child splits); fallback to fixed-size |
| `src/ingestion/cleanse.py` | PDF text cleansing: headers/footers, page numbers, boilerplate, hyphenation, irrelevant sections |
| `src/ingestion/parent_store.py` | JSON store of parent sections for expanded context retrieval |
| `src/memory/chat_memory.py` | Formats prior turns into prompt context (compact packing: recent Q+A + older Q-only) |

## LangGraph (orchestration)

| Module | Purpose |
|--------|---------|
| `src/graph/canonical_graph.py` | **Default production graph** — classify → strategy → retrieve/grade/rewrite loops → generate → verify → finalize |
| `src/graph/source_tools_graph.py` | **Tool-selected sources** — LLM binds PDF / DB / API / MCP / calculator; source hits CRAG-graded |
| `src/graph/shared_nodes.py` | Router invoke, direct answer, web search nodes |
| `src/graph/evidence_management.py` | Evidence grading, deduplication, candidate processing |
| `src/graph/context_builder.py` | Token-budgeted context construction for generation |
| `src/graph/verification_engine.py` | LLM judge + deterministic citation checks; abstention path |
| `src/graph/strategy_heuristics.py` | Strategy selection (single_hop, multi_hop, decompose, tools, …) |
| `src/graph/canonical_state.py` | `CanonicalGraphState` — graph runtime state helpers |
| `src/contracts/state.py` | `CanonicalAgentState` — API/runner state contract |

**Removed (Phase 7):** legacy mode graphs (`router_graph`, `crag_graph`, `decompose_graph`, `multi_hop_graph`, `tools_graph`, `agent_graph`, `consensus_graph`) and the baseline RAG module. See [LEGACY_RETIREMENT_INVENTORY.md](./LEGACY_RETIREMENT_INVENTORY.md).

## Schemas & Response Building

| Module | Purpose |
|--------|---------|
| `src/schemas.py` | Dataclasses: `AgentResponse` (answer, mode, sources, citations, context_docs, follow_ups), `Citation` (index, chunk_id, source, page, section, snippet, score) |
| `src/retrieval/citations.py` | `build_response()` — assembles response with consistent citations, context, and sources from documents |
| `src/evaluation/metrics.py` | RAGAS-inspired LLM-as-judge (faithfulness, relevance, context precision) |
| `src/evaluation/retrieval_metrics.py` | Golden-set hit-rate / recall@k / MRR vs `data/eval/golden_qa.json` |

## Everything Else (not LangChain/LangGraph)

These wrap the AI core with what's needed to run it safely in production. They don't call
OpenAI or LangChain directly — they gate what reaches/leaves the chains above.

| Module | Purpose |
|--------|---------|
| `src/runner.py` | Single dispatch — privacy → input guardrails → optional Redis cache → cost budget → **canonical or source_tools graph** → follow-ups → output guardrails/privacy → cache write |
| `src/streaming.py` | ContextVar emitter + `stream_text` / `run_graph_streaming` for progressive SSE |
| `src/guardrails.py` | Input validation, output validation, rate limiting, token/cost budget, quality checks (`RateLimitError`) |
| `src/privacy.py` | PII/PHI regex detection, redaction, policy |
| `src/config.py` | Settings via pydantic-settings (ingestion, retrieval, LLM/Groq, cache, circuit breakers, API, memory, observability) |
| `src/cache/redis_cache.py` | Optional answer cache (`CACHE_ENABLED`), idempotency keys, shared Redis client |
| `src/resilience/circuit_breaker.py` | In-process closed → open → half-open breakers (rerank, web search) |
| `src/api/server.py` | FastAPI — `/query`, `/query/stream`, `/kb`, `/mcp`, `/health`, `/health/ready`, `/modes`, `/metrics` |
| `src/api/health.py` | Liveness/readiness (Chroma, OpenAI key, Redis, extra sources, optional Groq/NVIDIA/Supabase) |
| `src/api/security.py` | API key auth dependency (constant-time compare, mandatory in production) |
| `src/api/rate_limit.py` | Per-client sliding-window limiter — Redis when `RATE_LIMIT_BACKEND` is `auto` or `redis`, else memory |
| `src/api/metrics.py` | Prometheus counters/histograms (requests, latency, cache, LLM fallback, rate limits) |
| `src/memory/supabase_store.py` | Optional persistent chat history (sync client — callers run it via `asyncio.to_thread`) |
| `src/observability.py` / `src/bootstrap.py` | LangSmith: env bootstrap + parent span `agent_request:<mode>` nesting retrieve, grade, graph, follow-ups |
| `monitoring/` | Prometheus scrape config + Grafana dashboard provisioning for local/compose |

## Pattern

```
LangGraph StateGraph (canonical_graph.py | source_tools_graph.py)
  └── nodes call LangChain chains & tools
  └── conditional edges for routing, retry loops, verification (canonical)
  └── source_tools: agent ⇄ tools (CRAG-grade source hits) → finalize
  └── CanonicalAgentState with reducers for evidence, steps, citations

src.runner.run_agent() / stream_agent()  ← single entry for CLI / API / UIs
  └── guardrails + privacy + optional Redis cache
  └── dispatches to ask_canonical() or ask_source_tools()
  └── token usage tracked via LangChain's get_openai_callback()
  └── follow-ups + citations assembled into AgentResponse
```

Never call OpenAI or DuckDuckGo directly — always go through LangChain abstractions. Never
call `ask_canonical`, `ask_source_tools`, or graph nodes directly from CLI/API/UI code — always go through
`src.runner.run_agent()` or `stream_agent()`, or guardrails, privacy, and caching are silently skipped.
