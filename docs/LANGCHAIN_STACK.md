# LangChain & LangGraph Stack Conventions

Every AI component in this project uses **LangChain** or **LangGraph**.

## LangChain (building blocks)

| Module | Purpose |
|--------|---------|
| `src/prompts.py` | `ChatPromptTemplate` for all prompts |
| `src/chains/generation.py` | LCEL chains: `prompt \| llm \| StrOutputParser()` |
| `src/agents/router.py` | `router_chain` with structured output |
| `src/agents/grader.py` | `grader_chain` — grades each chunk (Phase 3) |
| `src/agents/query_rewriter.py` | `rewrite_chain` — query rewrite on failed retrieval |
| `src/agents/decomposer.py` | `decompose_chain` — splits complex questions (Phase 4) |
| `src/agents/multi_hop.py` | `analyze_chain`, `reflect_chain` — sequential hops (Phase 5) |
| `src/retrieval/` | `VectorStoreRetriever` via `.as_retriever()` |
| `src/tools/` | `@tool` decorated tools |
| `src/llm.py` | `ChatOpenAI` |
| `src/ingestion/` | Document loaders, text splitters, Chroma |

## LangGraph (orchestration)

| Module | Purpose |
|--------|---------|
| `src/graph/router_graph.py` | Phase 2 — route → direct / retrieve / web |
| `src/graph/crag_graph.py` | Phase 3 — retrieve → grade → retry loop → fallback |
| `src/graph/decompose_graph.py` | Phase 4 — decompose → parallel retrieve → synthesize |
| `src/tools/all_tools.py` | `retrieve_docs`, `web_search`, `calculator` tools |
| `src/agents/orchestrator.py` | `choose_strategy` — analyzes question for best pattern |
| `src/graph/agent_graph.py` | Phase 7 — full orchestrator with strategy selection |

## Pattern

```
LangGraph StateGraph
  └── nodes call LangChain chains & tools
  └── conditional edges for routing & loops
  └── Annotated[list, operator.add] for step logs
```

Never call OpenAI or DuckDuckGo directly — always go through LangChain abstractions.
