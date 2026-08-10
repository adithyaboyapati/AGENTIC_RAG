# LangSmith Setup — Quick Reference

5-minute checklist to enable tracing. For usage, viewing traces, and troubleshooting, see
the comprehensive guide: [LANGSMITH_TRACING.md](LANGSMITH_TRACING.md).

## 1. Get an API Key

1. Sign up at [smith.langchain.com](https://smith.langchain.com)
2. Settings → API Keys → Create new key

## 2. Configure `.env`

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_pt_your-key-here
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_PROJECT=agentic-rag
```

> **Never commit a real key to a doc, screenshot, or git history — even in a private
> repo.** Treat any key that was ever pasted in plaintext as compromised and rotate it.

## 3. Verify

```bash
python -c "
from src.observability import is_tracing_enabled
from src.config import settings
print('Tracing:', is_tracing_enabled())
print('Project:', settings.langsmith_project)
"
```

## 4. Run Anything

Tracing initializes automatically — `src/bootstrap.py` calls
`init_langsmith_tracing()` before any LangChain module loads, and every entry point
(`src/cli.py`, `src/api/server.py`, React UI via the API, `streamlit_app.py`) imports it
first. No code changes needed per-query:

```bash
python -m src.cli ask "What is Self-RAG?" --mode crag -v
```

Then view the trace at [smith.langchain.com](https://smith.langchain.com), project
matching `LANGSMITH_PROJECT`.

## Separate Projects per Environment

```bash
# .env (development)
LANGSMITH_PROJECT=agentic-rag-dev

# .env.production
LANGSMITH_PROJECT=agentic-rag-prod
```

See [LANGSMITH_TRACING.md](LANGSMITH_TRACING.md) for trace structure, cost analysis,
custom tracing with `traced_execution()`, and troubleshooting.
