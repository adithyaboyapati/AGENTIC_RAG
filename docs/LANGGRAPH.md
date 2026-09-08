# LangGraph — Current Graphs (v1)

**Status: CURRENT** — production graphs in `src/graph/canonical_graph.py` and `src/graph/source_tools_graph.py`.

> Historical note: [LANGGRAPH_DEEP_DIVE.md](../LANGGRAPH_DEEP_DIVE.md) documents the **removed** seven-graph architecture (Phases 2–8). Do not use it for production behavior.

## Terminology

| Term | Meaning in this repo |
|------|---------------------|
| **Agent** | An LLM that makes a decision (router, grader, strategy selector, verifier when LLM enabled) |
| **Workflow / Graph** | The compiled LangGraph `StateGraph` — deterministic control flow |
| **Node** | A Python function registered on the graph; may call agents or deterministic code |
| **Tool** | LangChain `@tool` callable. Canonical path uses federation, not LLM tool selection. `source_tools` mode lets the LLM pick PDF / DB / API / MCP / calculator |
| **Application function** | Deterministic code: `retrieve()`, rerank, evidence processing, citation mapping |
| **State** | `CanonicalAgentState` carried through the graph |
| **Edge** | Fixed transition between nodes |
| **Conditional edge** | Branch on state (route, grade outcome, strategy) |

## State model

Production state is **`CanonicalAgentState`** (`src/contracts/state.py`), serialized through `CanonicalGraphState` (`src/graph/canonical_state.py`).

Key fields:

| Field | Role |
|-------|------|
| `original_question` | Immutable user question |
| `route` | `direct` \| `retrieve` \| `web_search` |
| `strategy` | `simple` \| `decompose` \| `multi_hop` |
| `strategy_decision_source` | `heuristic` \| `llm` |
| `retrieval_plan` / `retrieval_results` | Deterministic retrieval boundary |
| `evidence` | Graded evidence with provenance |
| `generation_evidence_ids` | Exact evidence used for generation |
| `citations` | User-facing citation objects linked to evidence |
| `verification` | `VerificationResult` |
| `response_status` | `answered` \| `answered_with_warning` \| `abstained` |
| `retry_count` | CRAG-style rewrite attempts |
| `trace` | Append-only `TraceEvent` log |

Legacy state types (`RouterState`, `CRAGState`, `AgentState`, etc.) were **removed** in Phase 7.

## Graph topology

```mermaid
flowchart TD
    START --> classify
    classify -->|direct| direct_answer
    classify -->|web_search| web_search
    classify -->|retrieve| strategy_select
    strategy_select --> plan_retrieval
    plan_retrieval --> retrieve
    retrieve --> grade
    grade -->|pass| context
    grade -->|rewrite| rewrite
    grade -->|fallback| web_fallback
    rewrite --> plan_retrieval
    context --> generate
    generate --> verify
    direct_answer --> verify
    web_search --> verify
    web_fallback --> verify
    verify --> finalize
    finalize --> END
    classify -->|abort| abort
    abort --> END
```

Built by `build_canonical_graph()` in `src/graph/canonical_graph.py`.

## Nodes

| Node | Type | Module | Responsibility |
|------|------|--------|----------------|
| `classify` | Agent + fallback | `shared_nodes.invoke_router` | Route: direct / retrieve / web |
| `direct_answer` | Agent | `shared_nodes.run_direct_answer` | Answer without retrieval |
| `web_search` | Agent + tool | `shared_nodes.run_web_search_answer` | Web search + synthesis |
| `strategy_select` | Agent/heuristic | `strategy_heuristics.select_strategy` | Pick simple / decompose / multi_hop |
| `plan_retrieval` | Deterministic | `retrieval/canonical_adapter.build_retrieval_plan` | Build retrieval plan |
| `retrieve` | Deterministic | `canonical_adapter.execute_retrieval_plan` | Hybrid retrieve + federation |
| `grade` | Agent | `evidence_management.process_evidence_candidates` | Grade / filter evidence |
| `rewrite` | Agent | `query_rewriter.rewrite_query` | Reformulate on failed grade |
| `reflect` | Agent | `multi_hop.reflect_on_hop` | Multi-hop sufficiency (when used) |
| `context` | Deterministic | `context_builder.build_generation_context` | Context + token budget |
| `generate` | Agent | `rag_chain` via `stream_text` | Grounded generation |
| `verify` | Agent + rules | `verification_engine.verify_response` | Faithfulness / relevance |
| `finalize` | Deterministic | `citation_mapper`, response assembly | Citations + status |
| `abort` | Deterministic | Safe user message | Guardrail / gate abort |
| `web_fallback` | Agent + tool | Same as web search path | Grade failure fallback |

## Conditional edges

1. **After `classify`:** route → direct_answer | web_search | strategy_select | abort
2. **After `grade`:** sufficient evidence → context; retry budget → rewrite; else → web_fallback
3. **After `rewrite`:** always → plan_retrieval (retrieve again)
4. **Strategy-specific:** decompose / multi_hop expand the retrieval plan before `retrieve`

## Retry behavior

- `retry_count` increments on rewrite
- Bounded by `settings.max_retrieval_retries` (config)
- Ineffective retries are tracked in Phase 8 observations (`ineffective_retry_rate`)

## Strategy selection

`src/graph/strategy_heuristics.py`:

1. **Heuristic first** — regex patterns for compare/decompose, sequential multi-hop, simple definitional
2. **LLM fallback** — `orchestrator.choose_strategy()` when heuristics are inconclusive
3. **Force override** — deprecated API modes map to `force_strategy` via `src/runner_modes.py`

## Verification

`src/graph/verification_engine.py`:

- Rule-based checks on evidence linkage
- Optional LLM judge when `canonical_verification_llm_enabled=true`
- Sets `response_status` and may trigger abstention

## Streaming

`run_agent()` / `stream_agent()` emit SSE via `src/streaming.py`. Canonical runs use `ask_canonical()`; tool-selected runs use `ask_source_tools()`. Tokens and pipeline stages go to `/query/stream`. Debug **Tool Selection** and **Reranking** stages light up from tool steps and `grade_summary`.

## Source-tools graph (`mode=source_tools`)

Separate compiled graph: `src/graph/source_tools_graph.py` (`pipeline_version=source-tools-v1`).

```text
START → agent (bind_tools) ⇄ tools → finalize → END
```

| Tool | What it queries | Graded? |
|------|-----------------|---------|
| `retrieve_pdf` | Indexed PDF corpus only (`include_extra=False`) | Yes — CRAG `grade_documents` |
| `query_database` | SQLite research catalog | Yes |
| `query_api` | Ops catalog (`/kb`) | Yes |
| `query_mcp` | Lab notes MCP | Yes |
| `calculator` | AST-safe arithmetic | No |

If every chunk is graded out, the tool returns `[TOOL_EMPTY] No relevant evidence after grading` so the agent can try another source. Grader failures fail open (keep retrieved chunks). Bounded by `SOURCE_TOOLS_MAX_ROUNDS` (default 4).

## What is NOT in the canonical graph

- Separate compiled graphs per deprecated mode (router, crag, decompose, tools, consensus) — **removed**
- In-graph ReAct tool loop on the **canonical** path — extra sources federate into `retrieve()` instead
- LLM-selectable retrieval tools **inside canonical** — use `mode=source_tools` for that

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the full request path.
