# API Reference (Current)

**Status: CURRENT** — derived from `src/api/server.py` and `src/api/documents.py`.

Base URL: `http://localhost:8000` (dev). Frontend dev proxy: `/api/*` → backend.

## Authentication

When `REQUIRE_API_KEY=true` (mandatory in `ENVIRONMENT=production`):

```http
X-API-Key: <your-api-key>
```

Public without key: `GET /health` only.

## Health & metrics

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness |
| GET | `/health/ready` | Readiness (Chroma, Redis, extra sources, …) |
| GET | `/metrics` | Prometheus scrape (auth required) |

## Query

| Method | Path | Description |
|--------|------|-------------|
| POST | `/query` | Synchronous query |
| POST | `/query/stream` | SSE streaming query |
| GET | `/modes` | Production modes (`canonical`, `source_tools`). Deprecated aliases still accepted on `/query`. |
| GET | `/config` | Runtime config for UI (models, retrieval, flags) |

### Request body (`QueryRequest`)

```json
{
  "question": "What is corrective RAG?",
  "mode": "canonical",
  "session_id": "optional-session-id",
  "use_memory": true,
  "chat_history": [{"role": "user", "content": "..."}],
  "tenant_id": "default",
  "user_roles": ["public"]
}
```

**Public modes (`GET /modes`):** `canonical` (preferred) and `source_tools`. Legacy values (`agentic`, `baseline`, `crag`, …) are accepted on `/query`, mapped internally, and emit deprecation metrics.

### Response (`QueryResponse`)

| Field | Description |
|-------|-------------|
| `answer` | Generated answer |
| `citations` | Chunk-level provenance |
| `sources` | Human-readable source labels |
| `route` / `route_reason` | Routing and strategy summary; on `source_tools`, tool names used |
| `grade_summary` | CRAG grader summary (canonical evidence or source-tool hits) |
| `verification_status` | Verification outcome |
| `confidence` | Verification confidence when available |
| `response_status` | `answered`, `answered_with_warning`, `abstained`, or error |
| `pipeline_version` | `canonical-v1` or `source-tools-v1` |
| `request_id` | Correlation ID for feedback |
| `latency_ms` | Wall-clock latency |
| `error_code` | Set on guardrail abort or safe failure |

Streaming emits `step`, `token`, `pipeline`, `sources`, `answer`, `follow_ups`, `done`, `error` SSE events.

## Documents & ingestion

| Method | Path | Description |
|--------|------|-------------|
| GET | `/documents` | List indexed documents |
| DELETE | `/documents?source=` | Delete document chunks by source |
| POST | `/ingest/upload` | Upload PDFs (multipart) |
| POST | `/ingest/jobs` | Queue ingest job by path |
| GET | `/ingest/jobs/{job_id}` | Job status |
| GET | `/ingest/jobs` | List recent jobs |

## Feedback

| Method | Path | Description |
|--------|------|-------------|
| POST | `/feedback` | Thumbs up/down + optional categories/comment |
| GET | `/feedback/summary` | Aggregated ratings (operator) |
| GET | `/feedback` | Recent feedback rows (operator) |

Feedback ties to `request_id`, `pipeline_version`, and verification fields when provided by the client.

## Operator / ops

| Method | Path | Description |
|--------|------|-------------|
| GET | `/ops/preflight` | Pre-canary dependency check |
| GET | `/ops/canary/dashboard` | Canary rollout dashboard |
| GET | `/ops/canary/gates` | Promotion / rollback / cutover gates |
| GET | `/ops/legacy/retirement` | Legacy retirement readiness |
| GET | `/ops/quality/dashboard` | Phase 8 quality dashboard |
| GET | `/ops/eval/runs` | Evaluation run history |
| GET | `/ops/eval/cases` | Regression/golden case queue |
| POST | `/ops/eval/run` | Trigger scheduled or failure-driven eval |
| GET | `/ops/drift` | Quality + retrieval drift report |
| GET | `/ops/experiments` | Experiment registry |
| GET | `/ops/documents/freshness?source=` | Document version freshness |

## Auxiliary routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/kb` | Sample ops catalog (when enabled) |
| POST | `/mcp` | Lab MCP HTTP bridge (when enabled) |

## Error behavior

| Code | When |
|------|------|
| 401 | Missing/invalid API key |
| 429 | Rate limit exceeded |
| 503 | Concurrency ceiling (`Retry-After: 5`) |
| 422 | Validation error |

Canonical failure with legacy runtime disabled returns a **safe abstention** answer (not an empty 500).

See [PRODUCTION.md](./PRODUCTION.md) for deployment and [GUARDRAILS.md](./GUARDRAILS.md) for security controls.
