# Implementation Status — Agentic RAG Project

**Last Updated:** August 4, 2026  
**Phases Complete:** 0–5 (foundation + 5 agentic patterns)  
**Phases Pending:** 6–8 (tools, unified orchestration, production)

## Quick Summary

✅ **Working Now (Phases 0–5)**
- Baseline RAG (naive fixed pipeline)
- Query Router (agent decides if/how to retrieve)
- Corrective RAG (agent grades docs, rewrites query, retries)
- Query Decomposition (agent splits complex Qs into parallel sub-queries)
- Multi-Hop Retrieval (agent chains sequential retrievals)
- Streamlit UI (chat interface with agent trace visibility)

⏳ **Planned Next (Phases 6–8)**
- Tool-Augmented Agent (calculator, web search, vector DB as tools)
- Full Orchestration (unified graph combining all patterns)
- Production API (FastAPI, evaluation, observability)

## How to Use

### 1. Streamlit UI (recommended for learning)
```bash
cd /Users/adithyaboyapati/Desktop/cur/Agentic_RAG
source activate bapi_lang
streamlit run streamlit_app.py
```
- Opens at http://localhost:8501
- Chat interface with agent trace visibility
- Dropdown to select phase (1–5)

### 2. CLI (for quick testing)
```bash
python -m src.cli ask "Your question" --mode crag --verbose
```
Modes: `baseline`, `router`, `crag`, `decompose`, `multi_hop`

### 3. Python API (for integration)
```python
from src.runner import run_agent

result = run_agent("What is Self-RAG?", "crag")
print(result.answer)
print(result.steps)  # see agent decision trail
```

## Architecture Overview

```
LangChain (building blocks)          LangGraph (orchestration)
├── ChatPromptTemplate                ├── Phase 1: Linear pipeline
├── LCEL chains                       ├── Phase 2: Routing (conditional edges)
├── VectorStoreRetriever              ├── Phase 3: CRAG loop (conditional edges)
├── @tool decorators                  ├── Phase 4: Map-reduce (Send API)
└── Structured output (Pydantic)      └── Phase 5: Sequential loop (conditional edges)

Both backed by ChromaDB vector store (singleton) and OpenAI LLM
```

## File Structure (Key Files)

```
src/
├── runner.py              ← Unified dispatcher (CLI + Streamlit use this)
├── config.py              ← Settings (env vars)
├── llm.py                 ← ChatOpenAI singleton
├── schemas.py             ← AgentResponse dataclass
├── prompts.py             ← All ChatPromptTemplate definitions
│
├── chains/
│   └── generation.py      ← LCEL chains (rag, direct, synthesis, web)
│
├── agents/
│   ├── router.py          ← router_chain (Phase 2)
│   ├── grader.py          ← grader_chain (Phase 3)
│   ├── decomposer.py      ← decompose_chain (Phase 4)
│   └── multi_hop.py       ← analyze + reflect chains (Phase 5)
│
├── graph/
│   ├── router_graph.py    ← Phase 2 routing agent
│   ├── crag_graph.py      ← Phase 3 CRAG loop
│   ├── decompose_graph.py ← Phase 4 parallel retrieval
│   └── multi_hop_graph.py ← Phase 5 sequential hops
│
├── rag/
│   └── baseline.py        ← Phase 1 (fixed pipeline)
│
├── tools/
│   └── web_search.py      ← @tool wrapper around DuckDuckGo
│
└── retrieval/
    └── retriever.py       ← VectorStoreRetriever (singleton)

streamlit_app.py           ← Streamlit UI
src/cli.py                 ← CLI entry point
```

## Phases Explained

### Phase 1: Baseline RAG
- **Pattern:** Always retrieve → always generate
- **Learning:** See what you're improving
- **Limitations:** No routing, no grading, no retry logic

### Phase 2: Query Router
- **Pattern:** Agent decides — direct answer, retrieve, or web search
- **Learning:** First agentic decision (conditional routing)
- **Gains:** Skips unnecessary retrieval for ~20–30% of queries

### Phase 3: Corrective RAG (CRAG)
- **Pattern:** Retrieve → grade → [retry if bad | web fallback | generate]
- **Learning:** Self-evaluation loop; agent is critic of its own retrieval
- **Gains:** Biggest quality jump; handles noisy docs

### Phase 4: Query Decomposition
- **Pattern:** Decompose complex Q → parallel retrieve each sub-Q → synthesize
- **Learning:** Map-reduce (parallel execution via LangGraph `Send`)
- **Gains:** Multi-part comparisons handled well

### Phase 5: Multi-Hop Retrieval
- **Pattern:** Sequential hops where Hop N+1 depends on Hop N's findings
- **Learning:** Sequential loops (vs Phase 4's parallel); reflection points
- **Gains:** Entity-detail chains ("Find CRAG, then find its fallback")

## Comparison: Baseline vs Agentic

**Question:** "Compare naive RAG, advanced RAG, and modular RAG"

**Phase 1 (Baseline):**
- Single retrieval pass
- Gets ~4 chunks, may miss some aspects
- Shallow comparison

**Phase 4 (Decompose):**
- 3 parallel sub-queries: "What is naive RAG?", "What is advanced RAG?", "What is modular RAG?"
- Retrieves 4 chunks for each
- Synthesizes into structured comparison with sections

## Next Steps

### To Continue Learning (Phase 6)
Implement tool-calling:
- Agent picks tools dynamically (retrieve, web search, calculator)
- LangChain function calling + tool definitions
- Expand beyond RAG

### To Go Full Production (Phase 7–8)
- Unify all patterns into one StateGraph
- Add FastAPI REST API
- Implement evaluation metrics (RAGAS)
- Add observability & logging

## Testing & Validation

### Quick Validation Tests
```bash
# Baseline should retrieve even for "Hello"
python -m src.cli ask "Hello!" --mode baseline --verbose

# Router should skip retrieval for "Hello"
python -m src.cli ask "Hello!" --mode router --verbose

# CRAG should show grading + retry
python -m src.cli ask "Obscure question" --mode crag --verbose

# Decompose should split into sub-queries
python -m src.cli ask "Compare X, Y, and Z" --mode decompose --verbose

# Multi-hop should chain hops sequentially
python -m src.cli ask "What does CRAG use as fallback?" --mode multi_hop --verbose
```

### Evaluation (Phase 8)
Once Phase 8 is implemented, run:
```bash
python -m src.evaluation.run_eval
```

Will show:
- Context Precision (are retrieved docs relevant?)
- Faithfulness (is answer grounded in docs?)
- Answer Relevance (does it answer the question?)
- Latency (how fast per mode?)
- Cost (token usage)

## Key Design Patterns

### Singletons
- `get_llm()` — ChatOpenAI (reused)
- `get_vector_store()` — ChromaDB (reused)
- `get_retriever()` — VectorStoreRetriever (thread-safe, reused)

**Why:** Parallel LangGraph workers need shared clients.

### Structured Output
All LLM "decisions" use Pydantic:
- `RouteDecision` (Phase 2) — route: "direct" | "retrieve" | "web_search"
- `DocumentGrade` (Phase 3) — relevant: bool, score: 0–1
- `DecompositionResult` (Phase 4) — sub_queries: list[str]
- `MultiHopAnalysis` (Phase 5) — needs_multi_hop: bool, first_search_query: str

**Why:** Reliable parsing, type safety, easy to extend.

### LCEL Chains
All text generation uses LCEL (Langsmith Composable Expression Language):
```python
chain = PROMPT | llm | StrOutputParser()
answer = chain.invoke({"key": value})
```

**Why:** Composable, streamable, easy to trace.

## Troubleshooting

### ChromaDB singleton errors
If parallel retrievals fail, ensure `src/retrieval/retriever.py` is using cached singleton with threading lock.

### LLM API errors
Check `.env` has valid `OPENAI_API_KEY`.

### Web search not working
Run `pip install ddgs` for DuckDuckGo support.

### Streamlit won't start
```bash
pip install streamlit
streamlit run streamlit_app.py
```

## Learning Resources in Repo

1. **[docs/CONCEPTS.md](docs/CONCEPTS.md)** — 10min read on RAG vs Agentic RAG
2. **[docs/ROADMAP.md](docs/ROADMAP.md)** — Phase-by-phase breakdown with examples
3. **[docs/LANGCHAIN_STACK.md](docs/LANGCHAIN_STACK.md)** — Architecture patterns

## Questions?

See the Streamlit UI "Agent Steps" panel — it shows the full decision trail of any query.
