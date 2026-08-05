"""
Phase 8: Production Deployment Guide

This document covers deploying Agentic RAG to production.

## Quick Start (Local)

### Run the API

```bash
# 1. Set environment variables
cp .env.example .env
# Edit .env with your OPENAI_API_KEY

# 2. Ingest knowledge base (one-time)
python -m src.ingestion.ingest --source data/sample_docs

# 3. Start API server
uvicorn src.api.server:app --host 0.0.0.0 --port 8000

# 4. Test the API
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is Self-RAG?", "mode": "agentic"}'
```

### Run Evaluation

```bash
python -m src.evaluation.run_eval
```

This tests all 7 modes on 4 sample questions and outputs `eval_results.json` with latency metrics.

## Docker Deployment

### Build & Run

```bash
# Build image
docker build -t agentic-rag:latest .

# Run container
docker run -p 8000:8000 \
  -e OPENAI_API_KEY=sk-... \
  -v ./data/chroma_db:/app/data/chroma_db \
  agentic-rag:latest
```

### Docker Compose (Recommended)

```bash
# Set environment
cp .env.production .env

# Start services
docker-compose up -d

# View logs
docker-compose logs -f agentic-rag

# Stop
docker-compose down
```

## API Endpoints

### Health Check

```bash
GET /health
→ {"status": "healthy", "service": "agentic-rag"}
```

### List Modes

```bash
GET /modes
→ {"baseline": "Phase 1 — Baseline RAG", ...}
```

### Query (Synchronous)

```bash
POST /query

{
  "question": "What is Self-RAG?",
  "mode": "agentic"
}

→ {
  "question": "...",
  "mode": "agentic",
  "answer": "...",
  "sources": ["data/sample_docs/rag.pdf"],
  "steps": ["Router → retrieve", "Strategy: simple", ...],
  "latency_ms": 5234.0
}
```

### Query (Streaming)

```bash
POST /query/stream

# Returns Server-Sent Events (SSE) with steps and answer
curl -N http://localhost:8000/query/stream \
  -H "Content-Type: application/json" \
  -d '{"question": "What is Self-RAG?"}'
```

## Production Checklist

- [ ] Set `OPENAI_API_KEY` to production key
- [ ] Set `OPENAI_MODEL` to latest available (`gpt-4o` or better)
- [ ] Increase `RETRIEVAL_TOP_K` to 5-7 for better coverage
- [ ] Set `GRADER_RELEVANCE_THRESHOLD` to 0.6-0.7 for stricter filtering
- [ ] Enable LangSmith tracing (`LANGCHAIN_TRACING_V2=true`)
- [ ] Run evaluation suite (`python -m src.evaluation.run_eval`)
- [ ] Set up container health checks (included in Dockerfile)
- [ ] Configure logging and monitoring (optional: Postgres for logs)
- [ ] Test streaming endpoint for long queries
- [ ] Set up rate limiting (optional: add in FastAPI middleware)

## Monitoring

### Latency by Mode

From `eval_results.json` after running evaluation:
- `baseline` — ~1-2s (simple)
- `router` — ~2-3s (routing overhead)
- `crag` — ~3-4s (grading overhead)
- `decompose` — ~4-6s (parallel retrievals + synthesis)
- `multi_hop` — ~5-8s (sequential retrieval loop)
- `tools` — ~2-4s (function calling)
- `agentic` — ~3-8s (strategy-dependent)

### Cost per Query

Approximate OpenAI API costs (in USD):
- `baseline` → ~0.0005 (1-2 LLM calls)
- `agentic` → ~0.005-0.02 (5-15 LLM calls + strategy analysis)

Track actual costs using OpenAI billing dashboard or LangSmith.

## Scaling

For production scale:

1. **Multiple workers** — Docker Compose with `workers: 4` (adjust to CPU count)
2. **Caching** — Add Redis for embedding cache (see optional in docker-compose.yml)
3. **Database** — Add Postgres for query logging (see docker-compose.yml)
4. **Load balancing** — Use nginx or AWS ALB
5. **Auto-scaling** — Kubernetes deployment or AWS ECS

## Observability

### Enable LangSmith (Optional)

```bash
# Set in .env.production
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls_...
LANGCHAIN_PROJECT=agentic-rag-prod

# Then traces appear in LangSmith dashboard
```

### Logs

API logs go to stdout/stderr. In production, pipe to:
- CloudWatch (AWS)
- Stackdriver (GCP)
- Datadog
- ELK Stack

## Troubleshooting

### Query times out

- Check `OPENAI_API_KEY` is valid
- Check network connectivity
- Increase FastAPI timeout (set in server.py)

### Low quality answers

- Run `python -m src.evaluation.run_eval` to diagnose
- Increase `RETRIEVAL_TOP_K`
- Lower `GRADER_RELEVANCE_THRESHOLD`
- Re-ingest knowledge base if outdated

### High costs

- Use `gpt-3.5-turbo` instead of `gpt-4` (cheaper)
- Prefer `router` or `tools` modes (fewer LLM calls)
- Disable decomposition for simple questions

---

See README.md for full project context.
"""
