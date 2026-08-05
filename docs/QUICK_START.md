# Quick Start Guide — Agentic RAG

Get up and running with the complete 7-mode Agentic RAG system in 5 minutes.

---

## Installation

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up environment
cp .env.example .env
# Edit .env with your OpenAI API key

# 3. Ingest documents (already done with rag.pdf)
python -m src.ingestion.ingest --source data/sample_docs
```

---

## Run the System

### Option A: Interactive Streamlit App (Recommended)

```bash
streamlit run streamlit_app.py
```

Opens browser at http://localhost:8501 with:
- Mode selector (7 options)
- Chat interface
- Real-time agent traces
- Visualization of routes, decompositions, hops

### Option B: Command Line

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
```

### Option C: REST API

```bash
# Start server
python -m uvicorn src.api.server:app --reload --port 8000

# Query the API
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is Self-RAG?",
    "mode": "crag"
  }' | jq

# Check modes
curl http://localhost:8000/modes

# Health check
curl http://localhost:8000/health
```

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
# Run comprehensive RAGAS-inspired evaluation
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
├── src/
│   ├── config.py                 # Configuration
│   ├── llm.py                    # Shared LLM instance
│   ├── schemas.py                # Pydantic models
│   ├── prompts.py                # All prompt templates
│   ├── ingestion/
│   │   └── ingest.py            # PDF → chunks → vectors
│   ├── retrieval/
│   │   └── retriever.py         # Vector store access
│   ├── tools/
│   │   ├── web_search.py        # DuckDuckGo tool
│   │   └── all_tools.py         # Centralized tool definitions
│   ├── chains/
│   │   └── generation.py        # LCEL chains (RAG, synthesis, etc.)
│   ├── agents/
│   │   ├── router.py            # Phase 2: Query router
│   │   ├── grader.py            # Phase 3: Document grader
│   │   ├── query_rewriter.py    # Phase 3: Query rewriter
│   │   ├── decomposer.py        # Phase 4: Query decomposer
│   │   ├── multi_hop.py         # Phase 5: Multi-hop analyzer
│   │   └── orchestrator.py      # Phase 7: Strategy picker
│   ├── graph/
│   │   ├── router_graph.py      # Phase 2: LangGraph
│   │   ├── crag_graph.py        # Phase 3: LangGraph
│   │   ├── decompose_graph.py   # Phase 4: LangGraph
│   │   ├── multi_hop_graph.py   # Phase 5: LangGraph
│   │   ├── tools_graph.py       # Phase 6: LangGraph
│   │   └── agent_graph.py       # Phase 7: LangGraph
│   ├── rag/
│   │   └── baseline.py          # Phase 1: Baseline RAG
│   ├── runner.py                # Unified dispatcher
│   ├── cli.py                   # Command-line interface
│   ├── api/
│   │   └── server.py            # FastAPI REST server
│   └── evaluation/
│       ├── metrics.py           # Phase 8: RAGAS-inspired metrics
│       └── evaluate_all_modes.py# Phase 8: Comprehensive evaluation
├── streamlit_app.py             # Phase 6: Web UI
├── docs/
│   ├── CONCEPTS.md              # Learning concepts
│   ├── ROADMAP.md               # Phase-by-phase guide
│   └── LANGCHAIN_STACK.md       # Architecture reference
├── data/
│   ├── sample_docs/
│   │   └── rag.pdf             # Knowledge base
│   └── chroma_db/              # Vector store (auto-created)
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment template
├── Dockerfile                   # Production container
├── docker-compose.yml           # Local deployment
├── README.md                    # Project overview
├── PRODUCTION.md                # Deployment guide
├── EVALUATION_REPORT.md         # Phase 8 results
└── QUICK_START.md              # This file
```

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

- **Learning Path**: `docs/ROADMAP.md` (phases 0-8)
- **Architecture**: `docs/LANGCHAIN_STACK.md`
- **Production Deployment**: `PRODUCTION.md`
- **Evaluation Results**: `EVALUATION_REPORT.md`
- **Concepts & Theory**: `docs/CONCEPTS.md`

---

**Happy learning! 🚀**
