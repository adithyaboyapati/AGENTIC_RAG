# Production Guardrails — Safety, Rate Limiting, and Cost Control

**Purpose**: Protect the production system with automatic safety checks, rate limits, and
cost controls. All of this is enforced identically in the CLI, FastAPI, React UI, and
Streamlit — via the single choke point `src.runner.run_agent` / `stream_agent`.

---

## Overview

Guardrails are **automatic safety gates** that prevent:

✅ **Invalid or dangerous input** — malformed questions, credential leakage
✅ **Cost overruns** — excessive token usage and runaway spend
✅ **Resource exhaustion** — per-client and process-wide rate limiting
✅ **Low-quality output** — missing sources, degenerate answers, ungrounded claims

They live in two layers:

| Layer | Where | Scope |
|-------|-------|-------|
| Per-client rate limiting | `src/api/rate_limit.py` | HTTP only — keyed by API key or IP (Redis or memory) |
| Input/output/cost guardrails | `src/guardrails.py` | Shared by CLI, API, React UI, Streamlit via `run_agent` |

---

## Request Flow (in `src/runner.py`)

Every call to `run_agent()` executes guardrails in this order, **before** the LLM is ever
invoked for the user's actual question:

1. **Prompt Injection & Jailbreak Defense** — scans user input for direct jailbreak/injection patterns, system override attempts, delimiter hijacking, and base64/hex obfuscation (`src/security/injection.py`).
2. **Privacy check on input** — block if PII is present (see [PRIVACY_COMPLIANCE.md](PRIVACY_COMPLIANCE.md)).
3. **Input guardrails** — length, word count, credential-pattern detection (`src/guardrails.py`).
4. **Query-rate check** — process-wide queries/minute budget.
5. **Token-budget check** — process-wide tokens/minute and tokens/hour budget.
6. **Multi-Tenant Document RBAC** — filters retrieved documents by tenant ID and authorized user access groups.
7. Dispatch to the selected mode (with Node-Level Output Gates and Circuit Breakers), **tracking actual token usage** via LangChain's OpenAI callback.
8. **Output guardrails** — length, presence of sources, citation extraction.
9. **Prompt Leakage & Indirect Injection Output Scan** — verifies no system prompt leakage or markdown image exfiltration.
10. **Privacy check on output** — redact or block PII/PHI per policy.
11. (Optional) **Quality guardrails** — validate answer quality per configurable thresholds.

Steps 2–4 raise `ValueError` (guardrail violation) or `RateLimitError` (rate/budget
exceeded, mapped to HTTP 429 by the API layer). Callers should catch both:

```python
from src.guardrails import RateLimitError
from src.runner import run_agent

try:
    result = run_agent(question, mode="crag")
except RateLimitError as e:
    ...  # 429 — back off and retry later
except ValueError as e:
    ...  # 400 — fix the input
```

---

## 1. Input Guardrails

**What They Check** (`src/guardrails.py::InputGuardrails`):
- Question length: 3–3000 characters
- Word count: max 500 words
- **Credential-shaped strings** — not a keyword blocklist

### Why not a keyword blocklist?

An earlier version blocked any question containing words like `"secret"`, `"password"`,
or `"token"`. That rejected entirely legitimate questions — e.g. *"What is a token limit
in LLMs?"* — with no security benefit, since blocking the word "password" doesn't stop
someone from actually pasting a password.

Instead, `InputGuardrails.CREDENTIAL_PATTERNS` matches the **shape of real credentials**:

```python
CREDENTIAL_PATTERNS = [
    ("openai_key",        r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    ("aws_access_key",    r"\bAKIA[0-9A-Z]{16}\b"),
    ("github_token",      r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    ("private_key_block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("password_assignment", r"\bpassword\s*[:=]\s*\S+"),
    ("api_key_assignment",  r"\bapi[_-]?key\s*[:=]\s*\S+"),
    ("bearer_token",        r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}"),
]
```

```python
from src.guardrails import InputGuardrails

# Passes — legitimate question about tokens
InputGuardrails.validate("What is a token limit in LLMs?")  # (True, [])

# Blocked — looks like an actual leaked credential
InputGuardrails.validate("my key is sk-abcdefghijklmnop1234567890")
# (False, [GuardrailViolation(rule="blocked_keyword", ...)])
```

**Example Violations**:
```
❌ min_length: Question too short (minimum 3 characters)
❌ max_length: Question too long (maximum 3000 characters)
❌ max_words: Question too many words (maximum 500)
❌ blocked_keyword: Question appears to contain a credential (openai_key) — remove it
❌ instruction_override: Instruction override attempt detected (ignore_previous_instructions)
❌ jailbreak: Jailbreak or persona bypass attempt detected (dan_persona)
```

---

## 2. Jailbreak & Prompt Injection Defense

**What It Protects Against** (`src/security/injection.py::InjectionDetector`):
- **Direct Instruction Overrides**: "Ignore all previous instructions...", "Disregard prior directives...", "[SYSTEM OVERRIDE]", role resetting.
- **Jailbreak Personas & Modes**: DAN (Do Anything Now), AIM, STAN, Developer Mode, unrestricted persona simulations, ethical constraint removal.
- **System Prompt Extraction**: Requests asking the LLM to dump, repeat verbatim, or leak system prompts/internal instructions.
- **Adversarial Framing & Obfuscation**: Base64/Hex/ROT13 encoding, zero-width space evasion, unicode homoglyph normalization.
- **Indirect Prompt Injection**: Poisoned context inside retrieved documents, web search results, or tool outputs (quarantined via `src/resilience/node_gate.py`).
- **Markdown Data Exfiltration**: Malicious markdown images trying to leak user data or tokens to external collector servers.

### False-Positive Resistance
The engine distinguishes between attacks and legitimate educational or security inquiries. Questions like *"What is a prompt injection attack?"* or *"Explain how DAN jailbreaks work"* pass without false positives.

### Configuration (`.env`)
```bash
INJECTION_GUARDRAILS_ENABLED=true     # Enable prompt injection and jailbreak scanning
INJECTION_GUARDRAILS_MODE=block       # block | warn | off
INDIRECT_INJECTION_PROTECTION_ENABLED=true # Scan retrieved docs and web snippets
PROMPT_LEAKAGE_DETECTION_ENABLED=true # Scan LLM output for system prompt leaks and exfil
```

---

## 3. Output Guardrails

**What They Check** (`src/guardrails.py::OutputGuardrails`):
- Answer length (10–10,000 characters)
- Presence of sources
- Confidence score, if supplied
- **Citation extraction** — validated chunk IDs, source documents, page numbers

```python
class OutputGuardrails:
    MIN_ANSWER_CHARS = 10
    MAX_ANSWER_CHARS = 10000
    MIN_CONFIDENCE = 0.5
```

```python
from src.guardrails import OutputGuardrails

valid, violations = OutputGuardrails.validate(
    answer=generated_answer,
    confidence=0.8,
    sources=retrieved_docs,
    citations=citation_list,  # new: Citation dataclass instances
)
```

All output-guardrail violations are currently **warnings** (logged, not blocking) — a
short or sourceless answer still reaches the user, but is flagged for review in logs.

Citations are **always extracted** (via `src/retrieval/citations.py`) so frontend and
evaluation pipeline have detailed source attribution (chunk ID, snippet, page, section).

---

## 3. Rate Limiting

### Per-client (HTTP layer — `src/api/rate_limit.py`)

A sliding-window limiter keyed by API key (if present) or client IP, applied as a FastAPI
dependency on `/query` and `/query/stream`:

```python
from src.api.rate_limit import enforce_client_rate_limit

@app.post("/query")
async def query(request: QueryRequest, _rate: None = Depends(enforce_client_rate_limit)):
    ...
```

Exceeding the limit returns **HTTP 429** with a `Retry-After` header. Configure via:

```bash
MAX_QUERIES_PER_MINUTE_PER_CLIENT=20
# auto — use Redis if reachable, else memory | redis | memory
RATE_LIMIT_BACKEND=auto
REDIS_URL=redis://localhost:6379/0
```

With `RATE_LIMIT_BACKEND=auto` (default) or `redis`, counters live in Redis and are shared
across API workers/replicas. If Redis is unreachable, the limiter falls back to in-memory
(per-process). Set `RATE_LIMIT_BACKEND=memory` explicitly for local tests / CI.
`docker-compose.yml` sets `RATE_LIMIT_BACKEND=redis` for the API service.

### Process-wide (shared layer — `src/guardrails.py::CostGuardrails`)

A backstop shared by every interface (CLI, API, Streamlit), regardless of who's calling:

```python
class CostGuardrails:
    def check_query_rate(self) -> tuple[bool, list[GuardrailViolation]]: ...
    def record_query(self) -> None: ...
```

Configure via `MAX_QUERIES_PER_MINUTE` (process-wide; distinct from the per-client limit
above).

---

## 4. Cost Guardrails (Token Budget)

**What They Track** (`src/guardrails.py::CostGuardrails`):
- Actual tokens used per query (via LangChain's OpenAI callback, not an estimate)
- Tokens per minute / tokens per hour, checked as a budget **before** each new query
- Cost in USD, using configurable per-1K-token pricing

```python
class CostGuardrails:
    def check_token_budget(self) -> tuple[bool, list[GuardrailViolation]]:
        """Reject new work if the minute/hour token budget is already spent."""

    def record_usage(self, input_tokens: int, output_tokens: int) -> None:
        """Record actual usage after a query completes."""

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """USD cost using settings.cost_per_1k_input_usd / cost_per_1k_output_usd."""

    def get_usage_stats(self) -> dict:
        """{'queries_per_minute', 'tokens_per_minute', 'tokens_per_hour', 'total_queries'}"""
```

This is wired into `src/runner.py::_run_with_cost_tracking`, which wraps every dispatch in
`get_openai_callback()`, records the real token counts, and logs cost per query:

```python
from src.guardrails import get_cost_tracker

tracker = get_cost_tracker()

ok, violations = tracker.check_token_budget()
if not ok:
    raise RateLimitError(violations[0].message)

# ... after the LLM call, with real usage from the callback ...
tracker.record_usage(input_tokens=cb.prompt_tokens, output_tokens=cb.completion_tokens)

stats = tracker.get_usage_stats()
cost = tracker.calculate_cost(cb.prompt_tokens, cb.completion_tokens)
```

**Configuration** (`.env`):
```bash
MAX_TOKENS_PER_QUERY=2000     # logged as a warning if exceeded (LLM max_tokens caps output separately)
MAX_TOKENS_PER_MINUTE=10000
MAX_TOKENS_PER_HOUR=100000
COST_PER_1K_INPUT_USD=0.00015   # gpt-4o-mini default pricing
COST_PER_1K_OUTPUT_USD=0.0006
```

### Hard caps at the LLM client level

Independent of the tracker above, every chat model (`src/llm.py`) is built with hard
`timeout`, `max_retries`, and `max_tokens`. The primary provider is OpenAI; when
`GROQ_API_KEY` is set and `LLM_FALLBACK_ENABLED=true`, failed primary calls (quota /
rate limit / outage) retry on Groq via LangChain `with_fallbacks`. Embeddings always
stay on OpenAI.

```python
ChatOpenAI(
    timeout=settings.openai_timeout_seconds,   # default 60s — kills hung calls
    max_retries=settings.openai_max_retries,   # default 2
    max_tokens=settings.max_output_tokens,     # default 1024 — caps completion size
)
# optional secondary: ChatGroq(...).with_fallbacks wiring in get_llm()
```

This matters because an API request that times out on the client side
(`REQUEST_TIMEOUT_SECONDS`) doesn't stop the worker thread — the LLM call itself must have
its own hard timeout, or an abandoned request keeps billing the provider after the caller
has already given up. Fallback activations increment `rag_llm_fallback_total` on `/metrics`.

---

## Integration Points

### In CLI (`src/cli.py`)
```python
from src.guardrails import RateLimitError
from src.runner import run_agent

try:
    result = run_agent(user_question, mode="crag")
except (ValueError, RateLimitError) as e:
    console.print(f"[red]{e}[/red]")
    sys.exit(1)
```

### In API (`src/api/server.py`)
```python
except RateLimitError as exc:
    raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": "60"})
except ValueError as exc:
    raise HTTPException(status_code=400, detail=str(exc))
```

### In Streamlit (`streamlit_app.py`)
```python
except (ValueError, RateLimitError) as exc:
    st.warning(str(exc))          # guardrail message is user-actionable
except Exception:
    st.error("Something went wrong…")  # never show raw exception text
```

---

## Quality Guardrails (Optional, Configurable)

`src/guardrails.py::QualityGuardrails` validates RAGAS-style metrics (faithfulness,
relevance, context precision) against thresholds. This is available in **two modes**:

### Offline Mode (Default — `QUALITY_GUARDRAILS_ENABLED=false`)

Quality checks are **not** wired into the live request path (to avoid latency/cost).
Use for offline/batch evaluation with `src/evaluation/metrics.py`:

```python
from src.evaluation.metrics import evaluate_metrics
from src.guardrails import QualityGuardrails

metrics = evaluate_metrics(question, answer, context)
valid, violations = QualityGuardrails.validate(
    faithfulness=metrics.faithfulness,
    relevance=metrics.answer_relevance,
    context_precision=metrics.context_precision,
)
```

Run `python -m src.evaluation.evaluate_all_modes` to score all 8 modes this way.

### Online Mode (Optional — `QUALITY_GUARDRAILS_ENABLED=true`)

When enabled, LLM-judged quality checks run on **every query** (adds ~2–3 sec latency
and extra LLM calls). If quality scores fall below thresholds, answers are flagged for
review or rejected. Configure via `.env`:

```bash
QUALITY_GUARDRAILS_ENABLED=true
QUALITY_MIN_FAITHFULNESS=0.7
QUALITY_MIN_RELEVANCE=0.6
QUALITY_MIN_CONTEXT_PRECISION=0.5
```

**Trade-off**: Ensures high-quality output but doubles query latency and cost. Recommended for
quality-critical applications (customer support) where latency is less critical than answer
correctness.

### Consensus-mode grounding (always on for `mode=consensus`)

Quality guardrails above are optional extra LLM judges. Consensus has **deterministic**
grounding checks in `src/graph/consensus_graph.py`:

- Debate is skipped when retrieval returns no documents.
- Prompts require abstention when chunks lack the asked comparison / example / metric.
- After the judge writes, sentences with weak lexical overlap vs the context are dropped.
- `consensus_score` defaults to **0.50** if unstated (not 0.92), and is capped after unsupported flags.
- Below `CONSENSUS_MIN_CONFIDENCE` a caveat is appended. Follow-ups are skipped on abstention.

This is still not span-level citation verification. Enable `QUALITY_GUARDRAILS_ENABLED` if you
also want an LLM faithfulness score on the live path.

### Golden Retrieval Evaluation

`src/evaluation/retrieval_metrics.py` scores retrieval against `data/eval/golden_qa.json`:
- **Hit rate** — did any expected keyword / chunk ID appear in the top-k?
- **Recall@k** — fraction of expected keywords/chunks recovered
- **MRR** — reciprocal rank of the first relevant hit

```bash
python -m src.evaluation.retrieval_metrics --offline   # CI gate (no embeddings)
python -m src.evaluation.retrieval_metrics             # live retrieve vs golden set
```

Citations (`src/schemas.py::Citation`) carry chunk ID, page, section, snippet, and score
so UI and evals can verify grounding independently of the LLM-as-judge metrics above.

---

## Testing Guardrails

```bash
pytest tests/test_guardrails.py tests/test_api.py -q
```

Key regression tests to be aware of:
- `test_input_accepts_questions_about_tokens_and_secrets` — guards against reintroducing the old keyword blocklist's false positives.
- `test_token_budget_blocks_when_exhausted` — guards against the token budget silently doing nothing.
- `test_query_rate_limit_returns_429` / `test_per_client_rate_limit` — guards against rate limits returning the wrong status code or not being enforced per-client.

---

## Production Deployment Checklist

- [ ] `REQUIRE_API_KEY=true` and `API_KEY` set (mandatory in production regardless — server refuses to start otherwise)
- [ ] `MAX_QUERIES_PER_MINUTE_PER_CLIENT` set to a realistic per-user budget
- [ ] `MAX_TOKENS_PER_MINUTE` / `MAX_TOKENS_PER_HOUR` set based on actual budget
- [ ] `COST_PER_1K_INPUT_USD` / `COST_PER_1K_OUTPUT_USD` match your actual model's pricing
- [ ] Decide on quality guardrails: `QUALITY_GUARDRAILS_ENABLED=false` (speed) or `true` (strict quality)
- [ ] If enabling quality guardrails, set thresholds (`QUALITY_MIN_FAITHFULNESS`, etc.) for your domain
- [ ] Confirm `429` responses include `Retry-After` and your client honors it
- [ ] Review guardrail violation logs for false positives after launch
- [ ] For multiple API workers/replicas, set `RATE_LIMIT_BACKEND=redis` (or leave `auto` with Redis up)
- [ ] Optional: `CACHE_ENABLED=true` + Redis for identical question+mode answer reuse
- [ ] Optional: `GROQ_API_KEY` for OpenAI failover
- [ ] Test citation extraction and source attribution with sample queries
- [ ] Confirm golden-set gate passes: `python -m src.evaluation.retrieval_metrics --offline`

---

## Summary

| Guardrail | Protects Against | Enforcement |
|-----------|-------------------|-------------|
| **Input** | Credential leakage, malformed input | Blocks (`ValueError`) |
| **Output** | Sourceless/degenerate answers | Warns (logged); citations tracked |
| **Per-client rate limit** | One client exhausting shared capacity | Blocks (HTTP 429); Redis-shared when configured |
| **Process rate/token budget** | Aggregate cost overruns | Blocks (`RateLimitError`) |
| **LLM timeout/max_tokens** | Runaway/abandoned calls still billing | Hard cap on OpenAI (and Groq fallback) client |
| **LLM fallback** | OpenAI outage / quota | Retries on Groq when keyed |
| **Quality** (offline) | Hallucinations, weak retrieval | `evaluate_all_modes` + golden retrieval metrics |
| **Quality** (online, optional) | Poor answer quality per LLM judge | Blocks/warns when `QUALITY_GUARDRAILS_ENABLED=true` |

**Enforced identically in CLI, API, React UI, and Streamlit** — all call through
`src.runner.run_agent` / `stream_agent`.
