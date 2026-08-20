# Contributing

## Setup

Use a virtualenv. The pins in `requirements.txt` are exact, and installing them
into a shared/conda base environment silently mixes versions — that is how the
test suite ends up uncollectable on a laptop while CI stays green.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install
cp .env.example .env    # then fill in OPENAI_API_KEY
```

Index the sample corpus once:

```bash
python -m src.ingestion.ingest --source data/sample_docs --reset
```

## The loop

```bash
ruff check src/ tests/ streamlit_app.py
pytest -q
```

Both must pass before you push; CI runs the same commands plus coverage,
`pip-audit`, `npm audit`, Trivy, and gitleaks.

## Conventions

- **Pins are deliberate.** Bump one, run the suite, commit the bump on its own.
  This applies to `requirements-dev.txt` too — an unpinned linter breaks CI on
  someone else's release day.
- **Comments explain why, not what.** The existing code is consistent about
  this; match it.
- **Config goes in `src/config.py`** as a typed `Settings` field with a comment
  and a matching entry in `.env.example`. Never read `os.environ` directly.
- **New settings that change behaviour need a test.** Especially anything that
  can reject a request.
- **Guardrail changes need false-positive tests.** An over-eager filter that
  corrupts correct answers is a worse bug than a missed match; see
  `tests/test_privacy.py` for the pattern.
- **Coverage is a ratchet.** `--cov-fail-under` sits just below the current
  number. If you raise coverage, raise the floor in `.github/workflows/ci.yml`.

## Adding an agent mode

1. Build the graph in `src/graph/`.
2. Register it in `MODE_LABELS`, `MODE_DESCRIPTIONS`, `EXAMPLE_QUESTIONS`, and
   `_dispatch` in `src/runner.py`.
3. Add the value to `AgentMode` in `src/api/server.py`.
4. Add a case to `tests/test_rag_graphs.py`.

Every mode inherits guardrails, privacy, caching, and cost tracking from
`run_agent` — do not re-implement them inside a graph.

## Load testing

```bash
pip install -r requirements-load.txt
locust -f tests/load/locustfile.py --host http://localhost:8000
```

## Security

Do not open a public issue for a vulnerability — see [SECURITY.md](SECURITY.md).
