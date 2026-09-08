# Agentic RAG — Frontend

React + Vite chat UI for the Agentic RAG FastAPI backend. Layout follows the
conventions of production chat apps (sidebar, centered thread, floating composer)
without copying any third-party implementation.

## Prerequisites

- Node.js 20+
- Backend running on `http://localhost:8000`

```bash
# from repo root
uvicorn src.api.server:app --reload --port 8000
```

## Setup

```bash
cd frontend
cp .env.example .env   # optional
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

In development, Vite proxies `/api/*` → `http://localhost:8000/*`.

## Environment

| Variable | Description |
|----------|-------------|
| `VITE_API_BASE_URL` | API origin. Leave empty in dev (uses `/api` proxy). |
| `VITE_API_KEY` | Sent as `X-API-Key` when the backend requires auth. Prefer injecting `API_KEY` via the Vite/nginx proxy instead. |

## What the UI talks to

The UI does not invent backend logic. It uses:

| Surface | API |
|---------|-----|
| Chat + streaming | `POST /query/stream` |
| Agent modes | `GET /modes` |
| Server model/retrieval settings | `GET /config` |
| Health | `GET /health`, `GET /health/ready` |
| Indexed documents | `GET /documents`, `DELETE /documents` |
| PDF upload | `POST /ingest/upload` → poll `GET /ingest/jobs/{id}` |
| Answer feedback | `POST /feedback` |
| Debug pipeline | SSE `pipeline` events from `/query/stream` |

## Features

- ChatGPT-style thread: user bubbles, assistant markdown, stop generation
- Conversation sidebar with search, rename, delete, grouped recency
- SSE streaming with retrieval/generation status
- Markdown + fenced code with copy
- Citation cards under answers (chunk, page, snippet, score)
- Document upload and index management
- Mode selector (`canonical` and `source_tools`) + read-only server configuration
- Error banner when the API is unreachable
- Developer/Debug panel: Query → Processing → **Tool Selection** → Retrieval → Chunks → Rerank → Context → Generation → Answer

## Project structure

```
frontend/src/
├── api/client.ts                 # fetch + SSE, documents, feedback
├── components/
│   ├── chat/                     # thread, markdown, citations, composer
│   ├── sidebar/                  # conversation list
│   ├── documents/                # upload + index
│   ├── settings/                 # mode + server config
│   ├── debug/                    # pipeline inspector
│   └── Header.tsx
├── hooks/useChat.ts
├── hooks/useDocuments.ts
├── lib/pipeline.ts               # live stage mapping
├── lib/chatStore.ts              # local conversation persistence
└── types.ts
```

## Scripts

```bash
npm run dev
npm run build
npm run preview
npm run lint
```

## Production

From the repo root, `docker compose up -d` builds this app, serves it on **:8080**,
and proxies `/api` (including PDF uploads up to 25 MB) to the API service.
