# Security Policy

## Reporting a vulnerability

Please report security issues privately via GitHub's **Report a vulnerability**
button under the Security tab, rather than opening a public issue. Include
reproduction steps and the affected version or commit. Expect an initial
response within 5 business days.

## Supported versions

The `main`/`prod` branch is the only supported version.

## Security model

**Trust boundaries**

| Input | Trust | Control |
|---|---|---|
| User question | Untrusted | Direct jailbreak/injection detector, credential/length guardrails, PII policy, API auth, rate limits |
| Retrieved chunks | Semi-trusted | Indirect injection scan, node gate quarantine, operator-ingested corpora |
| Web search results | Untrusted | Indirect injection scan, circuit breaker, node gates quarantine failures |
| LLM output | Untrusted | System prompt leakage detector, markdown exfiltration scan, output guardrails, privacy filter |
| Tool arguments | Untrusted | The calculator parses an AST allowlist — never `eval` |

**Controls in place**

- Jailbreak & Prompt Injection defense: multi-layer scanning for direct attacks (DAN, persona bypasses, instruction resets, obfuscated base64/hex/rot13 payloads) and indirect attacks (poisoned context, markdown exfiltration).
- Hardened system prompts with strict XML delimiter isolation and explicit instruction hierarchy.
- Constant-time API key comparison; auth mandatory in production.
- Production startup refuses wildcard CORS, short keys, and multi-worker
  deployments with per-worker (in-memory) budgets.
- `/metrics` and `/health/ready` are auth-gated by default; `/health` is public.
- Per-client and process-wide rate limits, plus token and cost budgets shared
  across workers via Redis.
- Concurrency ceiling with 503 backpressure so saturation cannot become
  unbounded queueing or unbounded LLM spend.
- Total wall-clock deadline on streaming responses; client disconnect
  cooperatively cancels the worker.
- Non-root container with no compiler in the runtime image; CI fails the build
  if a `.env` file, a root user, or `gcc` appears in the image.
- `pip-audit`, `npm audit`, Trivy, and gitleaks run in CI.

**Known limitations**

- The PII/PHI filter is regex-based. It is tuned to avoid corrupting legitimate
  technical text, which means it is not a compliance control on its own — see
  [docs/PRIVACY_COMPLIANCE.md](docs/PRIVACY_COMPLIANCE.md).
- Cost estimates use configured per-token rates and are approximations, not
  billing data.

## Secrets

Never commit `.env` or `.env.production`. Both are gitignored, blocked by a
pre-commit hook, excluded from the Docker image, and CI fails if one appears
inside a built image. In production, prefer a secret manager over a file on
disk; `deploy.sh` reads `.env.production` only as a single-host fallback.
