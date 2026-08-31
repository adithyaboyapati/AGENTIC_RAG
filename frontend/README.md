# Agentic RAG Lab — Frontend

React + Vite chat UI for the Agentic RAG FastAPI backend.

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

In development, Vite proxies `/api/*` → `http://localhost:8000/*`, so CORS is not required locally.

## Environment

| Variable | Description |
|----------|-------------|
| `VITE_API_BASE_URL` | API origin. Leave empty in dev (uses `/api` proxy). In production set to your API URL, e.g. `https://api.example.com`. |
| `VITE_API_KEY` | Sent as `X-API-Key` when the backend requires auth. If set to `"prompt"`, user is prompted for API key at runtime. |
| `VITE_ENABLE_MEMORY_CONTROLS` | Show memory UI controls (true/false). Default: true. |
| `VITE_SHOW_CITATIONS` | Render clickable source citations (true/false). Default: true. |
| `VITE_SHOW_FOLLOWUPS` | Show follow-up question chips (true/false). Default: true. |

## Scripts

```bash
npm run dev      # local development
npm run build    # production build → dist/
npm run preview  # preview production build
npm run lint     # oxlint
```

## Features

### Core
- **Eight agent modes** (Baseline, Router, CRAG, Decompose, Multi-Hop, Tools, Agentic, Consensus Debate) with descriptions and example prompts — Tools mode can hit the paper catalog, ops API, and lab MCP in addition to PDFs
- **Markdown chat** (GFM via `react-markdown`)
- **True SSE streaming** via `POST /query/stream` — live agent steps as nodes finish, answer tokens as they generate

### Quality, Attribution & Security
- **Multi-Agent Consensus Score** and Adversarial Critique badges
- **Multi-Tenant RBAC** support with isolated document access
- **Detailed source citations** — chunk ID, page, section, snippet, relevance score
- **Expandable agent traces** — route decision, grading, retrieval steps, latency, tenant info
- **Three grounded follow-up questions** — generated from retrieved sources

### Memory & Persistence
- **Chat history** persisted in browser IndexedDB across refreshes
- **Conversation memory** with session IDs (optional Supabase on the backend)
- **Memory controls** — `use_memory` and related options when enabled

### Design
- Custom CSS (`App.css` / `index.css`) — responsive layout for mobile, tablet, desktop
- System dark-mode preference supported where styles define it

## Project Structure

```
frontend/src/
├── api/client.ts           # fetch + SSE streamQuery
├── components/
│   ├── Sidebar.tsx         # Mode picker, history, memory controls
│   ├── ChatHistory.tsx     # Message list
│   ├── ChatMessage.tsx     # Markdown message + citations
│   ├── ChatInput.tsx       # Composer
│   ├── EmptyState.tsx      # First-run prompts
│   ├── FollowUps.tsx       # Follow-up chips
│   ├── Thinking.tsx        # In-flight step indicators
│   └── TracePanel.tsx      # Expandable agent trace
├── data/modes.ts           # Mode labels / example questions
├── hooks/useChat.ts        # Chat state + streaming
├── lib/chatStore.ts        # IndexedDB persistence
├── types.ts
├── App.tsx
├── App.css / index.css
└── main.tsx
```

## Production

### Static host

```bash
npm run build
# deploy dist/ to Vercel, Netlify, S3, etc.
# set VITE_API_BASE_URL (and VITE_API_KEY if needed) at build time
```

### Docker Compose (recommended with the API)

From the repo root, `docker compose up -d` builds this app with `frontend/Dockerfile`,
serves it on **:8080** via nginx, proxies `/api` to the `agentic-rag` service, and can
inject `API_KEY` server-side so the browser never holds the secret.

See [docs/PRODUCTION.md](../docs/PRODUCTION.md).

## Troubleshooting

### API connection error

- Ensure the backend is on `http://localhost:8000`
- Check `VITE_API_BASE_URL` in production builds
- Verify `CORS_ORIGINS` on the backend for non-proxied deployments

### Memory not persisting

- Confirm IndexedDB is enabled in the browser
- For cross-device memory, configure Supabase on the backend

### Follow-ups or citations not showing

- Check `VITE_SHOW_FOLLOWUPS` / `VITE_SHOW_CITATIONS`
- Confirm the API response includes `follow_ups` and `citations`
