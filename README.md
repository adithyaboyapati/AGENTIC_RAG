# Agentic RAG — Project-Based Learning

Build a **production-grade Agentic RAG system** from scratch and learn every concept hands-on.

## What You'll Build

A **Research Assistant** that goes far beyond "retrieve → generate":

```
User Question
     │
     ▼
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│ Query Router│────▶│ Query Decomposer │────▶│  Retriever  │
└─────────────┘     └──────────────────┘     └──────┬──────┘
     │                        │                      │
     │ direct answer          │ sub-queries            ▼
     ▼                        ▼               ┌─────────────┐
┌─────────────┐         (multi-hop)           │  Grader     │─── retry if bad
│  LLM Answer │                               └──────┬──────┘
└─────────────┘                                      │
                                                     ▼
                                              ┌─────────────┐
                                              │  Generator  │
                                              └─────────────┘
```

## RAG vs Agentic RAG (One-Line Summary)

| Traditional RAG | Agentic RAG |
|-----------------|-------------|
| Fixed pipeline: always retrieve → generate | **Agent decides** what to do at each step |
| One retrieval pass | **Adaptive** — retrieve 0, 1, or N times |
| No self-correction | **Evaluates** its own work and retries |
| Single query in, answer out | **Decomposes** complex queries into sub-tasks |
| Retrieval is the only tool | **Multiple tools** — search, calculator, APIs |

## Learning Phases

Work through these in order. Each phase adds one agentic capability.

| Phase | What You Build | Agentic Concept |
|-------|----------------|-----------------|
| **0** | Project setup, docs, eval harness | Foundation |
| **1** | Baseline RAG (naive pipeline) | Understand what you're improving |
| **2** | Query router | Agent decides *if* retrieval is needed |
| **3** | Corrective RAG (CRAG) | Agent grades docs, re-retrieves if bad |
| **4** | Query decomposition | Agent breaks complex questions apart |
| **5** | Multi-hop retrieval | Agent chains retrievals across steps |
| **6** | Tool-augmented agent | Web search, calculator, SQL beyond vectors |
| **7** | Full LangGraph orchestration | State machine, loops, human-in-the-loop |
| **8** | Production hardening | API, observability, evals, deployment |

See [docs/ROADMAP.md](docs/ROADMAP.md) for detailed milestones.

## Quick Start

```bash
# 1. Create virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Add your OPENAI_API_KEY (or other provider)

# 4. Ingest sample documents (if not already done)
python -m src.ingestion.ingest --source data/sample_docs

# 5a. Use Streamlit UI (Phases 1–5)
streamlit run streamlit_app.py
# Opens at http://localhost:8501 — chat interface with agent trace visibility

# 5b. Or use CLI (Phases 1–5)
python -m src.cli ask "What is corrective RAG?" --mode crag --verbose

# 5c. Try different modes
python -m src.cli ask "Hello!" --mode router --verbose
python -m src.cli ask "Compare naive RAG, advanced RAG, and modular RAG" --mode decompose --verbose
python -m src.cli ask "What fallback does CRAG use?" --mode multi_hop --verbose
```

## Project Structure

```
Agentic_RAG/
├── docs/
│   ├── CONCEPTS.md              # Deep dive: RAG vs Agentic RAG
│   ├── ROADMAP.md               # Phase-by-phase learning guide
│   └── LANGCHAIN_STACK.md        # LangChain + LangGraph patterns
├── data/
│   ├── sample_docs/             # PDF corpus (rag.pdf)
│   └── chroma_db/               # Vector store (auto-created)
├── src/
│   ├── config.py                # Settings & env vars
│   ├── llm.py                   # ChatOpenAI singleton
│   ├── schemas.py               # AgentResponse dataclass
│   ├── runner.py                # Unified agent dispatcher
│   ├── prompts.py               # ChatPromptTemplate library
│   ├── chains/
│   │   └── generation.py         # LCEL chains (rag, direct, synthesis, web)
│   ├── ingestion/
│   │   └── ingest.py            # PDF → chunks → ChromaDB
│   ├── retrieval/
│   │   └── retriever.py         # VectorStoreRetriever (singleton)
│   ├── agents/
│   │   ├── router.py            # router_chain (Phase 2)
│   │   ├── grader.py            # grader_chain (Phase 3)
│   │   ├── query_rewriter.py    # rewrite_chain (Phase 3)
│   │   ├── decomposer.py        # decompose_chain (Phase 4)
│   │   └── multi_hop.py         # analyze + reflect chains (Phase 5)
│   ├── graph/
│   │   ├── router_graph.py      # Phase 2 routing agent
│   │   ├── crag_graph.py        # Phase 3 corrective RAG loop
│   │   ├── decompose_graph.py   # Phase 4 map-reduce (parallel)
│   │   └── multi_hop_graph.py   # Phase 5 sequential hops
│   ├── tools/
│   │   ├── web_search.py        # @tool decorator (DuckDuckGo)
│   │   └── __init__.py
│   ├── rag/
│   │   └── baseline.py          # Phase 1 baseline
│   ├── evaluation/
│   │   └── run_eval.py          # (TODO Phase 8)
│   ├── api/
│   │   └── (TODO Phase 8)
│   └── cli.py                   # CLI entry point
├── streamlit_app.py             # Streamlit UI (Phases 1–5)
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md (this file)
```

## Key Concepts You'll Master

1. **Agentic loop** — Observe → Decide → Act → Evaluate → Repeat
2. **Query routing** — Not every question needs retrieval
3. **Self-RAG / CRAG** — Grade retrieved context before generating
4. **Query decomposition** — "Compare X and Y" → two sub-queries
5. **Multi-hop reasoning** — Answer A → retrieve for B → synthesize
6. **Tool use** — When vector DB isn't enough
7. **State graphs** — LangGraph for production agent orchestration
8. **Evaluation** — Measure retrieval quality, faithfulness, answer relevance

## Current Implementation Status

**Completed:** Phases 0–5 (baseline, router, CRAG, decomposition, multi-hop)  
**Tested:** All modes work via CLI and Streamlit UI  
**Pending:** Phases 6–8 (tools, full orchestration, production)

## Recommended Learning Path

1. **Read** [docs/CONCEPTS.md](docs/CONCEPTS.md) — Understand RAG vs Agentic RAG
2. **Read** [docs/ROADMAP.md](docs/ROADMAP.md) — Phase-by-phase milestones
3. **Explore** [docs/LANGCHAIN_STACK.md](docs/LANGCHAIN_STACK.md) — Architecture patterns
4. **Run Streamlit UI** — `streamlit run streamlit_app.py`
5. **Compare modes** on the same question:
   - Phase 1 baseline (always retrieves)
   - Phase 2 router ("Hello" → skips retrieval)
   - Phase 3 CRAG (grade + retry loop)
   - Phase 4 decompose ("Compare X, Y, Z" → parallel sub-queries)
   - Phase 5 multi-hop ("What fallback?" → sequential hops)

## Tech Stack

All AI logic uses **LangChain** (chains, prompts, retrievers, tools) and **LangGraph** (agent orchestration). See [docs/LANGCHAIN_STACK.md](docs/LANGCHAIN_STACK.md).

**Core AI**
- **LangGraph** — Agent orchestration (StateGraph with nodes, edges, loops)
- **LangChain** — LCEL chains, ChatPromptTemplate, retrievers, `@tool` tools
- **ChromaDB** — Local vector store (via `langchain-chroma`)
- **OpenAI** (default) — LLM + embeddings (via `langchain-openai`)

**Frontend**
- **Streamlit** — Chat UI with agent trace visibility
- **Rich** — Terminal formatting (CLI)

**Other**
- **PyMuPDF** — PDF ingestion
- **DuckDuckGo** — Web search fallback (Phase 2+)
- **FastAPI** — (Planned Phase 8)

## Development Notes

### Adding New Phases
Each new phase follows the same pattern:
1. **LangChain** chains/tools in `src/agents/` or `src/chains/`
2. **LangGraph** StateGraph in `src/graph/`
3. **CLI dispatch** in `src/cli.py`
4. **Streamlit integration** (auto-wired via `src/runner.py`)

### Running Tests
```bash
pytest tests/
```

### Debugging with Verbose Output
```bash
python -m src.cli ask "YOUR QUESTION" --mode crag --verbose
```

Shows router decision, grader summary, agent steps, and sources.

## Next Phase

**Phase 6: Tool-Augmented Agent** (upcoming)
- Agent picks tools via LangChain function calling
- Tools: vector retrieval, web search, calculator
- LangGraph agent with tool-calling node
