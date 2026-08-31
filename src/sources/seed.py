"""Demo knowledge unique to the database, sample API, and MCP sources.

These records are intentionally *not* in the PDF corpus: structured paper
metadata, live ops catalog facts, and unpublished lab experiments. Values are
labeled as an internal demo catalog so they are not mistaken for live metrics.
"""

from __future__ import annotations

PAPERS: list[dict] = [
    {
        "id": "crag",
        "title": "CRAG: Corrective Retrieval Augmented Generation",
        "authors": "Shi, Weijia et al.",
        "year": 2024,
        "venue": "ICLR",
        "doi": "10.demo/crag-2024",
        "citation_count": 1842,
        "topic": "corrective RAG web fallback",
        "summary": (
            "Internal catalog: CRAG grades retrieved documents and triggers a web-search "
            "fallback when confidence is low. Demo citation_count=1842, venue=ICLR 2024."
        ),
    },
    {
        "id": "self-rag",
        "title": "Self-RAG: Learning to Retrieve, Generate, and Critique",
        "authors": "Asai, Akari et al.",
        "year": 2024,
        "venue": "ICLR",
        "doi": "10.demo/self-rag-2024",
        "citation_count": 2104,
        "topic": "self-reflective retrieval tokens",
        "summary": (
            "Internal catalog: Self-RAG emits reflection tokens to decide when to retrieve "
            "and whether a generation is supported. Demo citation_count=2104."
        ),
    },
    {
        "id": "modular-rag",
        "title": "Modular RAG: Composable Retrieval Pipelines",
        "authors": "Gao, Yunfan et al.",
        "year": 2024,
        "venue": "arXiv survey companion",
        "doi": "10.demo/modular-rag-2024",
        "citation_count": 956,
        "topic": "modular rag orchestration",
        "summary": (
            "Internal catalog: Modular RAG decomposes indexing, retrieval, and generation "
            "into swappable operators. Demo citation_count=956."
        ),
    },
]

BENCHMARKS: list[dict] = [
    {
        "id": "bench-hybrid-marco",
        "system_name": "Hybrid-RAG (dense + BM25 + RRF)",
        "dataset": "MS MARCO Dev",
        "metric": "nDCG@10",
        "score": 0.71,
        "split": "dev",
        "measured_on": "2026-03-01",
        "notes": "Internal catalog: RRF k=60, candidate_k=20, FlashRank rerank on.",
    },
    {
        "id": "bench-bm25-marco",
        "system_name": "BM25-only",
        "dataset": "MS MARCO Dev",
        "metric": "nDCG@10",
        "score": 0.48,
        "split": "dev",
        "measured_on": "2026-03-01",
        "notes": "Internal catalog: lexical baseline, no dense embeddings.",
    },
    {
        "id": "bench-parent-nq",
        "system_name": "Parent-child dense retriever",
        "dataset": "Natural Questions",
        "metric": "recall@5",
        "score": 0.84,
        "split": "dev",
        "measured_on": "2026-04-12",
        "notes": "Internal catalog: child_chunk_size=500, expand_to_parent=true.",
    },
]

DEPLOYMENTS: list[dict] = [
    {
        "id": "deploy-acme",
        "organization": "Acme Health",
        "rag_pattern": "modular RAG",
        "latency_p95_ms": 180,
        "monthly_cost_usd": 4200,
        "corpus_size_docs": 2_400_000,
        "notes": "Internal catalog: production clinical FAQ assistant, 6 retriever replicas.",
    },
    {
        "id": "deploy-northwind",
        "organization": "Northwind Labs",
        "rag_pattern": "agentic RAG",
        "latency_p95_ms": 920,
        "monthly_cost_usd": 11000,
        "corpus_size_docs": 850_000,
        "notes": "Internal catalog: research copilot with CRAG grading and tool calling.",
    },
]

GLOSSARY: list[dict] = [
    {
        "term": "index_lag",
        "definition": (
            "Seconds between a document finishing ingest and becoming searchable in "
            "the hot index. retriever-prod SLO is 30 seconds."
        ),
    },
    {
        "term": "retrieval_sla",
        "definition": (
            "p95 retrieve() for retriever-prod must complete in under 400ms excluding LLM time."
        ),
    },
    {
        "term": "parent_expand",
        "definition": (
            "Ops flag: retrieve child chunks then expand to parent sections before generation."
        ),
    },
    {
        "term": "rrf_fusion",
        "definition": (
            "Reciprocal Rank Fusion of dense and BM25 lists. Production uses rrf_k=60."
        ),
    },
]

SYSTEMS: list[dict] = [
    {
        "id": "retriever-prod",
        "name": "Production retriever",
        "owner": "platform-search",
        "environment": "prod",
        "replicas": 6,
        "index_lag_seconds": 12,
        "status": "healthy",
        "oncall": "search-oncall",
    },
    {
        "id": "rerank-prod",
        "name": "Production reranker",
        "owner": "ml-platform",
        "environment": "prod",
        "replicas": 3,
        "index_lag_seconds": 0,
        "status": "degraded",
        "oncall": "ml-oncall",
    },
    {
        "id": "ingest-worker",
        "name": "Async ingest workers",
        "owner": "platform-search",
        "environment": "prod",
        "replicas": 2,
        "index_lag_seconds": 45,
        "status": "healthy",
        "oncall": "search-oncall",
    },
]

INCIDENTS: list[dict] = [
    {
        "id": "INC-1042",
        "service": "rerank-prod",
        "started_at": "2026-08-14T16:20:00Z",
        "severity": "sev-2",
        "summary": "rerank-prod p95 climbed to 2100ms against a 400ms SLO.",
        "resolution": (
            "Rolled back the NVIDIA rerank model pin to nv-rerankqa-mistral-4b-v3 "
            "and restored p95 to 360ms."
        ),
    },
    {
        "id": "INC-0988",
        "service": "retriever-prod",
        "started_at": "2026-07-02T09:05:00Z",
        "severity": "sev-3",
        "summary": "BM25 index served stale counts after a Chroma reset.",
        "resolution": "Ran the rb-bm25 runbook (invalidate BM25 cache and rebuild).",
    },
]

EXPERIMENTS: list[dict] = [
    {
        "id": "exp-42",
        "title": "Parent-child vs fixed 500-token chunking",
        "date": "2026-04-12",
        "conclusion": (
            "Parent-child chunking improved recall@5 by 12% versus fixed 500-token "
            "windows on Natural Questions and reduced p95 generation context by 8% "
            "because fewer redundant children were expanded."
        ),
        "metrics": "recall@5 +12%; p95 context tokens -8%",
    },
    {
        "id": "exp-17",
        "title": "RRF k ablation (k=10 vs k=60)",
        "date": "2026-03-01",
        "conclusion": (
            "RRF k=60 beat k=10 by 0.03 nDCG@10 on MS MARCO Dev with hybrid dense+BM25. "
            "k=10 over-weighted the first dense hit and starved BM25-only titles."
        ),
        "metrics": "nDCG@10 0.71 (k=60) vs 0.68 (k=10)",
    },
    {
        "id": "exp-08",
        "title": "FlashRank vs NVIDIA rerank",
        "date": "2026-05-20",
        "conclusion": (
            "NVIDIA llama-nemotron rerank gained +0.04 nDCG@10 over local FlashRank "
            "MiniLM at a +40ms p95 cost. Keep NVIDIA in prod; FlashRank is the offline fallback."
        ),
        "metrics": "nDCG@10 +0.04; p95 +40ms",
    },
]

RUNBOOKS: list[dict] = [
    {
        "id": "rb-bm25",
        "title": "Rebuild a stale BM25 index",
        "steps": (
            "1. Confirm Chroma collection count matches ingest logs. "
            "2. Call invalidate_bm25_cache() (or restart the API process). "
            "3. Issue a retrieve() with retrieval_search_type=hybrid; the BM25 index "
            "rebuilds lazily from the corpus. 4. Check logs for 'Built BM25 index over N chunks'."
        ),
    },
    {
        "id": "rb-chroma-empty",
        "title": "Vector store is empty after reset",
        "steps": (
            "1. Run python -m src.ingestion.ingest --source data/sample_docs. "
            "2. Hit /health/ready and confirm chroma document count > 0. "
            "3. If HTTP Chroma, verify CHROMA_HOST points at the compose service."
        ),
    },
]

LAB_NOTES: list[dict] = [
    {
        "id": "note-2026-03-12",
        "date": "2026-03-12",
        "author": "lab-search",
        "body": (
            "Do not expand parents when the query is a single named metric "
            "(nDCG, recall@k). Child chunks already hold the number; parents add noise."
        ),
    },
    {
        "id": "note-2026-04-02",
        "date": "2026-04-02",
        "author": "lab-search",
        "body": (
            "Unpublished ablations live on the lab MCP server, not in rag.pdf. "
            "Treat exp-* identifiers as MCP lookups."
        ),
    },
]
