# Learning Roadmap — Phase by Phase

**Status:** Phases 0–7 complete. Phase 8 evaluation in progress.

Each phase has **learning goals**, **what to build**, and **how to verify you understood it**.

## Quick Navigation

| Phase | Status | CLI | Streamlit |
|-------|--------|-----|-----------|
| 1 Baseline | ✅ Done | `--mode baseline` | Dropdown |
| 2 Router | ✅ Done | `--mode router` | Dropdown |
| 3 CRAG | ✅ Done | `--mode crag` | Dropdown |
| 4 Decompose | ✅ Done | `--mode decompose` | Dropdown |
| 5 Multi-hop | ✅ Done | `--mode multi_hop` | Dropdown |
| 6 Tools | ⏳ Pending | — | — |
| 7 Full Agent | ⏳ Pending | — | — |
| 8 Production | ⏳ Pending | — | — |

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

| Phase | Status | Files | Est. Time |
|-------|--------|-------|-----------|
| 0 Foundation | ✅ Done | config, ingestion, retrieval | 1 day |
| 1 Baseline RAG | ✅ Done | baseline.py | 1 day |
| 2 Router | ✅ Done | router.py, router_graph.py | 1 day |
| 3 CRAG | ✅ Done | grader.py, crag_graph.py | 1 day |
| 4 Decompose | ✅ Done | decomposer.py, decompose_graph.py | 1 day |
| 5 Multi-hop | ✅ Done | multi_hop.py, multi_hop_graph.py | 1 day |
| 6 Tools | ⏳ Pending | tools expansion | 1-2 days |
| 7 Full Agent | ⏳ Pending | unified agent_graph.py | 1-2 days |
| 8 Production | ⏳ Pending | api, evaluation, deployment | 2-3 days |
| **Total** | **6/8** | **1 week done, 2 weeks to go** | 10 days |

## How to Continue

After Phase 5, pick Phase 6 or 7:
- **Phase 6** teaches tool-calling and expanding beyond RAG
- **Phase 7** combines all patterns into one unified agent
- **Phase 8** is production-ready deployment

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
