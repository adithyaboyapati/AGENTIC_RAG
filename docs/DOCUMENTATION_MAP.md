# Documentation Map

**Source of truth:** the codebase (`src/`, `tests/`, `frontend/`). When docs disagree with code, the code wins.

Use this map to find the authoritative document for each topic.

| Topic | Canonical (current) | Secondary | Historical |
|-------|---------------------|-----------|------------|
| **Architecture** | [ARCHITECTURE.md](./ARCHITECTURE.md) | [BACKEND_END_TO_END_GUIDE.pdf](./BACKEND_END_TO_END_GUIDE.pdf) · [README.md](../README.md) | [ROADMAP.md](./ROADMAP.md) |
| **LangGraph** | [LANGGRAPH.md](./LANGGRAPH.md) | [LANGCHAIN_STACK.md](./LANGCHAIN_STACK.md) | [LANGGRAPH_DEEP_DIVE.md](../LANGGRAPH_DEEP_DIVE.md) |
| **Agentic AI concepts** | [CONCEPTS.md](./CONCEPTS.md) | [ARCHITECTURE.md](./ARCHITECTURE.md) | [AGENTIC_RAG_DEEP_DIVE.md](../AGENTIC_RAG_DEEP_DIVE.md) |
| **RAG / retrieval** | [ARCHITECTURE.md](./ARCHITECTURE.md) § Retrieval | [LANGCHAIN_STACK.md](./LANGCHAIN_STACK.md) | [AGENTIC_RAG_DEEP_DIVE.md](../AGENTIC_RAG_DEEP_DIVE.md) |
| **Agents vs workflows** | [LANGGRAPH.md](./LANGGRAPH.md) § Terminology | [CONCEPTS.md](./CONCEPTS.md) | — |
| **Security** | [GUARDRAILS.md](./GUARDRAILS.md), [PRIVACY_COMPLIANCE.md](./PRIVACY_COMPLIANCE.md) | [SECURITY.md](../SECURITY.md) | — |
| **Evaluation** | [EVALUATION.md](./EVALUATION.md), [PHASE8_CONTINUOUS_EVAL.md](./PHASE8_CONTINUOUS_EVAL.md) | [CANARY_ROLLOUT.md](./CANARY_ROLLOUT.md) | [archive/EVALUATION_REPORT.md](./archive/EVALUATION_REPORT.md) |
| **Deployment** | [PRODUCTION.md](./PRODUCTION.md) | [QUICK_START.md](./QUICK_START.md) | — |
| **API** | [API.md](./API.md) | [frontend/README.md](../frontend/README.md) | — |
| **Legacy retirement** | [LEGACY_RETIREMENT_INVENTORY.md](./LEGACY_RETIREMENT_INVENTORY.md) | [ARCHITECTURE.md](./ARCHITECTURE.md) | [ROADMAP.md](./ROADMAP.md) |
| **Roadmap / phases** | [ROADMAP.md](./ROADMAP.md) (with status labels) | — | [archive/](./archive/) |
| **Interview prep** | — | — | [INTERVIEW_WALKTHROUGH.md](../INTERVIEW_WALKTHROUGH.md) (historical) |
| **Observability** | [LANGSMITH_TRACING.md](./LANGSMITH_TRACING.md) | [ARCHITECTURE.md](./ARCHITECTURE.md) § Observability | — |
| **Configuration** | [PRODUCTION.md](./PRODUCTION.md), `src/config.py` | `.env.example` | — |

## Current production summary

```text
Client → FastAPI → Runner → Canonical Graph v1  (mode=canonical)
                           → Source-tools graph  (mode=source_tools)
                         → Response
```

- **Production graphs:** `src/graph/canonical_graph.py` (preferred) and `src/graph/source_tools_graph.py`
- **Canonical state:** `CanonicalAgentState` (`src/contracts/state.py`)
- **Public modes:** `canonical`, `source_tools` (`GET /modes`). Legacy mode strings still accepted on `/query`
- **Source-tools:** LLM selects PDF / DB / API / MCP / calculator; source-backed hits are CRAG-graded
- **Fallback:** safe abstention when canonical fails (`legacy_runtime_enabled=false` by default)
- **Observability:** LangSmith parent span `agent_request:<mode>` nests retrieve, grade, graph, and follow-ups
- **Continuous evaluation:** Phase 8 loop (`src/evaluation/continuous_eval.py`, `GET /ops/quality/dashboard`)

## Historical documents

These preserve learning value from the multi-graph migration (Phases 1–7). They describe **earlier** architectures unless explicitly marked otherwise:

- [ROADMAP.md](./ROADMAP.md) — phase-by-phase build history
- [AGENTIC_RAG_DEEP_DIVE.md](../AGENTIC_RAG_DEEP_DIVE.md) — pre-canonical runtime deep dive
- [LANGGRAPH_DEEP_DIVE.md](../LANGGRAPH_DEEP_DIVE.md) — seven legacy StateGraphs
- [INTERVIEW_WALKTHROUGH.md](../INTERVIEW_WALKTHROUGH.md) — walkthrough of legacy mode dispatch
- [docs/archive/](./archive/) — completion snapshots from earlier milestones

## Obsolete — candidate for removal

| Document | Reason |
|----------|--------|
| [archive/PHASE_8_SUMMARY.md](./archive/PHASE_8_SUMMARY.md) | Refers to old "Phase 8 = consensus agent"; superseded by canonical + continuous eval docs |
| [archive/IMPLEMENTATION_STATUS.md](./archive/IMPLEMENTATION_STATUS.md) | Stale milestone checklist |
| [archive/PROJECT_COMPLETE.md](./archive/PROJECT_COMPLETE.md) | Pre-canonical completion snapshot |

Do not delete without team review — they may still help explain evolution.

## Documentation consistency test

```bash
pytest tests/test_documentation_consistency.py -q
```

Detects references to deleted graph files in **current** docs and broken local links.
