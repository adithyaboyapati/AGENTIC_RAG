# RAG vs Agentic RAG — Complete Conceptual Guide

This document demystifies Agentic RAG. Read it before writing code.

---

## Traditional RAG: A Fixed Pipeline

Traditional RAG is **not intelligent** — it's a **fixed recipe**:

```
Question → Embed → Search Vector DB → Stuff into Prompt → LLM → Answer
```

Every question goes through the same steps. The system never asks:

- "Do I even need to search?"
- "Are these documents good enough?"
- "Should I search again with a different query?"
- "Is this question too complex for one search?"

### What Traditional RAG Does Well

- Simple factual Q&A over a document corpus
- Low latency (one LLM call + one retrieval)
- Predictable cost



### Where Traditional RAG Breaks


| Scenario                                                                        | What Happens                                               |
| ------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| "What's 2+2?"                                                                   | Wastes a retrieval call; may retrieve irrelevant docs      |
| "Compare RAG vs Fine-tuning"                                                    | Single retrieval misses one side of the comparison         |
| Retrieved docs are irrelevant                                                   | LLM hallucinates or gives a vague answer anyway            |
| "What did our CEO say last week?"                                               | Vector DB has no recent data — agent should use web search |
| Multi-step: "Who founded the company in doc X and what's their latest project?" | Needs two retrievals chained together                      |


---



## Agentic RAG: An Agent That Uses RAG as a Tool

**Agentic RAG** wraps retrieval inside an **autonomous decision loop**. The LLM (agent) decides:

1. **Whether** to retrieve (routing)
2. **What** to retrieve (query rewriting, decomposition)
3. **How** to retrieve (semantic vs keyword vs web)
4. **If** the results are good enough (grading / self-evaluation)
5. **When** to retry or try a different strategy (corrective loop)
6. **Which tools** to use beyond vector search

```
                    ┌─────────────────────────────────┐
                    │         AGENT (LLM)             │
                    │  "What should I do next?"       │
                    └───────────────┬─────────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              ▼                     ▼                     ▼
        ┌──────────┐         ┌──────────┐         ┌──────────┐
        │ Retrieve │         │ Web Search│        │ Calculate│
        │ (Vector) │         │          │         │          │
        └────┬─────┘         └──────────┘         └──────────┘
             │
             ▼
        ┌──────────┐
        │  Grade   │─── bad? ──▶ rewrite query ──▶ retrieve again
        │  Docs    │
        └────┬─────┘
             │ good
             ▼
        ┌──────────┐
        │ Generate │
        │  Answer  │
        └──────────┘
```

The agent **uses RAG** — but RAG is one tool among many, not the entire system.

---



## The 6 Agentic Patterns (What Makes It "Agentic")



### 1. Query Routing

**Problem:** Not every question needs retrieval.

```
"Hello"           → respond directly (no retrieval)
"What is RAG?"    → retrieve from knowledge base
"Latest AI news"  → web search (not in your docs)
```

**Agentic behavior:** LLM classifies intent and picks a path.

---



### 2. Corrective RAG (CRAG) / Self-RAG

**Problem:** Retrieved documents may be irrelevant or incomplete.

**Agentic behavior:**

1. Retrieve documents
2. **Grade** each document: relevant / irrelevant
3. If mostly irrelevant → rewrite query and re-retrieve, OR fall back to web search
4. If relevant → proceed to generation

This is the single biggest quality improvement over naive RAG.

---



### 3. Query Decomposition

**Problem:** Complex questions need multiple pieces of information.

```
Question: "How does Agentic RAG differ from traditional RAG in terms of latency and cost?"

Decomposed:
  → Sub-Q1: "What is the latency profile of traditional RAG?"
  → Sub-Q2: "What is the latency profile of Agentic RAG?"
  → Sub-Q3: "What are the cost differences?"
  → Synthesize all sub-answers
```

**Agentic behavior:** LLM breaks the question apart, retrieves for each sub-question, then synthesizes.

---



### 4. Multi-Hop Retrieval

**Problem:** Some answers require chaining — answer from step 1 informs step 2.

```
Question: "What framework does the author of our LangGraph guide recommend for production?"

Hop 1: Retrieve → find author name
Hop 2: Retrieve → find author's production recommendations
Hop 3: Synthesize
```

**Agentic behavior:** Agent uses intermediate results to formulate the next retrieval query.

---



### 5. Tool Use Beyond Retrieval

**Problem:** Vector DB only knows what's indexed.


| Tool             | When Agent Uses It             |
| ---------------- | ------------------------------ |
| Vector retrieval | Questions about your documents |
| Web search       | Recent events, external facts  |
| Calculator       | Numeric computation            |
| SQL/API          | Structured data queries        |
| Code interpreter | Data analysis tasks            |


**Agentic behavior:** Agent picks the right tool for each sub-task.

---



### 6. Orchestration with State (LangGraph)

**Problem:** Real agents need loops, branching, memory, and human approval.

Traditional code:

```python
docs = retrieve(query)
answer = generate(query, docs)  # linear, no loops
```

Agentic orchestration (LangGraph):

```python
State = { query, documents, grade, sub_queries, answer, ... }

graph:
  route → retrieve → grade → [retry | generate | web_search]
                              ↑__________|
                              (loop until good enough)
```

**Agentic behavior:** Explicit state machine with conditional edges and cycles.

---



## Side-by-Side Comparison


| Dimension                 | Traditional RAG       | Agentic RAG                           |
| ------------------------- | --------------------- | ------------------------------------- |
| Control flow              | Fixed linear pipeline | Dynamic graph with branches & loops   |
| Retrieval                 | Always once           | 0 to N times, adaptive                |
| Query handling            | Single query as-is    | Rewrite, decompose, expand            |
| Quality check             | None                  | Self-grade retrieved context          |
| Tools                     | Vector DB only        | Vector DB + web + APIs + more         |
| Latency                   | Lower (1 pass)        | Higher (multiple LLM calls)           |
| Cost                      | Lower                 | Higher (more LLM reasoning steps)     |
| Quality on hard questions | Poor                  | Significantly better                  |
| Production readiness      | Demo-level            | Needs observability, evals, fallbacks |


---



## When to Use Which

**Use Traditional RAG when:**

- Simple FAQ over a stable document set
- Latency and cost are critical
- Questions are mostly single-fact lookups

**Use Agentic RAG when:**

- Questions are complex, multi-part, or comparative
- Document quality/noise is a concern (need grading)
- You need web search + docs combined
- Answer quality matters more than speed
- You're building a production assistant, not a demo

---



## Mental Model

> **Traditional RAG** = a search engine glued to an LLM.
>
> **Agentic RAG** = an LLM that *knows when and how* to search, *checks if search worked*, and *keeps trying* until it has enough context — using RAG as one of its capabilities.

---



## Papers & References (Optional Deep Dives)


| Paper               | Concept                                     |
| ------------------- | ------------------------------------------- |
| Self-RAG (2023)     | Self-reflection on retrieval and generation |
| CRAG (2024)         | Corrective retrieval with web fallback      |
| Adaptive-RAG (2024) | Route queries by complexity                 |
| LangGraph docs      | Production agent orchestration              |


---



## Modern Production Additions

### Hybrid Retrieval + Cross-Encoder Reranking

First-stage search is cheap but noisy. Production pipelines usually:

```
Over-fetch candidates (dense + BM25 / RRF)
  → Cross-encoder rerank (query + passage scored together)
  → Keep top_k for the LLM
```

This project does exactly that in `src/retrieval/`:

- **Hybrid retrieve** — dense embeddings + BM25 fused with Reciprocal Rank Fusion
- **Rerank** — NVIDIA `llama-nemotron-rerank-vl-1b-v2` (API) or local FlashRank
- **CRAG grading** (later) — LLM relevance filter that can rewrite / web-fallback

Rerank improves *ordering* of what enters the context window; CRAG decides whether that
context is *good enough*. They complement each other.

### Citation & Grounding

Once you have answers, you need to know **which chunks they came from**. The system now
tracks citations:

```
Citation = {
  index: 1,
  chunk_id: "sha256-...",
  source: "rag.pdf",
  page: 5,
  section: "3.2 Grading",
  snippet: "The grader assigns each chunk a relevance score...",
  score: 0.92  # usually the rerank score when reranking is enabled
}
```

Every answer includes a list of `Citation` objects. The frontend renders them as
clickable source links. Evaluation pipelines use them to measure **answer grounding** —
does each claim in the answer have a source to back it up?

### Follow-Up Questions

After answering, the system can generate 3 grounded follow-up questions:

```
User: "What is Self-RAG?"
Answer: "Self-RAG is..."
Follow-ups:
  1. "How does Self-RAG compare to CRAG?"
  2. "What are the computational costs of Self-RAG?"
  3. "Can Self-RAG be combined with web search?"
```

These are generated from the original answer + source snippets, so they stay relevant
and grounded. No more random suggestions.

### 7. Multi-Agent Consensus & Adversarial Debate

When factual precision is mission-critical (compliance, legal, medical), single-agent answers can overlook nuances or propagate subtle hallucinations:

```
User Query ──▶ [Retrieve & Compress]
                     │
                     ▼
           [Proposer Agent] ──▶ Drafts initial thesis with citations
                     │
                     ▼
        [Adversarial Critic] ──▶ Probes for ungrounded claims & missing nuances
                     │
                     ▼
         [Consensus Judge] ──▶ Arbitrates debate, strips unproven assertions,
                               and assigns Consensus Confidence Score (0.0–1.0)
```

Accessible via `--mode consensus`, this ensures answers are vetted under adversarial debate before reaching the user.

### 8. Multimodal Ingestion & Dynamic Context Compression

Real enterprise documents contain rich tabular matrices and visual diagrams:
- **PyMuPDF Structured Table Parser** converts raw PDF grids into clean GitHub-flavored Markdown tables.
- **Dynamic Context Compression** performs sentence-level token pruning against the query, stripping 30–50% of irrelevant tokens while retaining all critical facts and citations.

### 9. Semantic Vector Caching & Tenant Isolation

- **Vector Semantic Caching** calculates cosine similarity ($\ge 0.94$) against embedding queries, returning sub-millisecond cached responses without LLM spend.
- **Document RBAC** strictly isolates data per tenant and user role at both vector and BM25 sparse retrieval stages.

### Resilience & Ops (Production Layer)

Beyond the RAG graphs themselves, the serving path now includes:

- **Redis answer cache & Vector Semantic Cache** — identical or semantically equivalent questions skip retrieval/LLM with strict RBAC segregation
- **Groq LLM fallback** — OpenAI quota/outage retries on a secondary chat provider
- **Circuit breakers** — NVIDIA rerank and web search fail fast when upstreams are unhealthy
- **Prometheus metrics** — request latency, cache events, fallbacks, rate-limit hits, ingestion throughput
- **SSE streaming** — agent steps and answer tokens as they happen
- **Asynchronous Ingestion Worker Queue** — background PDF ingestion with progress tracking and HMAC webhooks

These don't change *what* Agentic RAG decides; they make the same agent safe and
observable under real traffic. See [PRODUCTION.md](PRODUCTION.md).

---

## What You'll Feel in This Project

After building all phases, run the same question through Phase 1 (baseline) and Phase 7 (full agent):

```
"Compare the latency trade-offs of traditional RAG vs Agentic RAG,
 and tell me which pattern Self-RAG uses for grading."
```

- **Phase 1 (baseline):** Hybrid retrieve → rerank → generate. May still miss multi-part coverage; weaker on comparisons.
- **Phase 7 (agentic):** Routes → decomposes into 3 sub-questions → retrieves + reranks for each → grades docs → synthesizes a complete answer with **detailed citations**. Generates 3 follow-up questions from the sources.

That difference — **adaptive, self-correcting, multi-step, and grounded** — is Agentic RAG.