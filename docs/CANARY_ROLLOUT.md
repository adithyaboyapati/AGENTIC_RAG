# Canary Rollout Operations

Phase 6 introduced shadow/canary controls for validating the canonical pipeline before full traffic. **As of Phase 7, canonical is primary** (`CANONICAL_PRIMARY=true`); legacy runtime is disabled by default (`LEGACY_RUNTIME_ENABLED=false`). Safe abstention replaces legacy graph fallback when canonical fails.

See also: [LEGACY_RETIREMENT_INVENTORY.md](./LEGACY_RETIREMENT_INVENTORY.md) · [EVALUATION.md](./EVALUATION.md)

## Defaults (safe)

| Setting | Default |
|---------|---------|
| `CANONICAL_PRIMARY` | `true` |
| `LEGACY_RUNTIME_ENABLED` | `false` |
| `LEGACY_FALLBACK_ENABLED` | `false` |
| `SHADOW_ENABLED` | `false` |
| `SHADOW_SAMPLING_RATE` | `0.0` |
| `CANARY_ENABLED` | `false` |
| `CANARY_STAGE` | `0` |
| `CANARY_PERCENT` | `0.0` |
| `CANARY_ALLOW_WARN_RESPONSES` | `false` |

No automatic promotion occurs. Each stage increase is an explicit operator decision after gate evaluation.

## Rollout stages

```text
Stage 0 — Pre-canary validation
Stage 1 — Shadow evidence collection (≥30 paired samples recommended)
Stage 2 — 1% canonical canary
Stage 3 — 5% canonical canary
Stage 4 — 25% canonical canary
Stage 5 — 50% canonical canary
Stage 6 — 100% canonical traffic
Stage 7 — Legacy retirement complete (graphs removed; safe abstention fallback)
```

Map stage to traffic with `CANARY_STAGE`:

| `CANARY_STAGE` | User-visible canonical % |
|----------------|--------------------------|
| `0` | 0% |
| `1` | 1% |
| `5` | 5% |
| `25` | 25% |
| `50` | 50% |
| `100` | 100% |

Alternatively set `CANARY_PERCENT` directly when not using stage labels.

## Enable shadow

Collect paired legacy + canonical evidence without exposing canonical answers:

```bash
export SHADOW_ENABLED=true
export SHADOW_SAMPLING_RATE=0.10   # 10% of requests
export CANARY_ENABLED=false
export CANARY_STAGE=0
```

Verify preflight and evidence gates:

```bash
curl -H "X-API-Key: $API_KEY" http://localhost:8000/ops/preflight
curl -H "X-API-Key: $API_KEY" http://localhost:8000/ops/canary/gates
```

Shadow requires ≥30 paired records before canary promotion (`SHADOW_MINIMUM_SAMPLES`, default 30).

## Disable shadow

```bash
export SHADOW_ENABLED=false
export SHADOW_SAMPLING_RATE=0.0
```

## Enable 1% canary

Only after shadow evidence gates pass:

```bash
export CANARY_ENABLED=true
export CANARY_STAGE=1
export SHADOW_ENABLED=true          # keep collecting paired data
export SHADOW_SAMPLING_RATE=0.25    # optional continued shadow on non-canary traffic
```

Run preflight for canary dependencies:

```bash
curl -H "X-API-Key: $API_KEY" "http://localhost:8000/ops/preflight?for_canary=true"
```

## Increase canary percentage

Increase stage explicitly after promotion gates pass:

```bash
# 1% → 5% → 25% → 50% → 100%
export CANARY_STAGE=5
```

Hold period settings (optional):

| Setting | Purpose |
|---------|---------|
| `CANARY_MINIMUM_SAMPLES` | Minimum canary paired samples before promotion (default 30) |
| `CANARY_MINIMUM_OBSERVATION_WINDOW_SECONDS` | Minimum wall-clock observation per stage (default 3600) |

Check gates before each increase:

```bash
curl -H "X-API-Key: $API_KEY" http://localhost:8000/ops/canary/gates
```

## Evaluate gates

Operator endpoints:

| Endpoint | Purpose |
|----------|---------|
| `GET /ops/preflight` | Dependency validation |
| `GET /ops/canary/gates` | Shadow, promotion, rollback, cutover gates |
| `GET /ops/canary/dashboard` | Traffic, quality, performance, economics summary |

Gate categories: quality, citation, retrieval, reliability, performance, economics, security.

## Roll back

### Emergency kill switch (no redeploy)

Runtime kill switch stops new canary assignments immediately:

```python
from src.evaluation.canary_rollout import kill_canary
kill_canary()
```

Or via environment (requires process reload in typical deployments):

```bash
export CANARY_ENABLED=false
export CANARY_STAGE=0
export CANARY_PERCENT=0.0
```

Automatic rollback triggers when hard rollback gates fire (security violation, abnormal fallback rate, severe latency regression). This invokes the runtime kill switch.

## Full cutover

100% user-visible canonical traffic:

```bash
export CANARY_ENABLED=true
export CANARY_STAGE=100
export CANONICAL_PRIMARY=true
export LEGACY_RUNTIME_ENABLED=false
export LEGACY_FALLBACK_ENABLED=false
```

Evaluate full cutover readiness:

```bash
curl -H "X-API-Key: $API_KEY" http://localhost:8000/ops/canary/gates
```

Look for `cutover.recommendation: READY_FOR_FULL_CUTOVER`.

Legacy graph modules were removed in Phase 7. Fallback is **safe abstention**, not legacy graph replay.

## Required monitoring

Prometheus metrics (scrape `/metrics` with API key if gated):

| Metric | Labels |
|--------|--------|
| `rag_canary_requests_total` | `stage` |
| `rag_canary_success_total` | `stage` |
| `rag_canary_failures_total` | `stage` |
| `rag_canary_fallback_total` | `stage`, `fallback_reason` |
| `rag_canary_canonical_wins_total` | `stage`, `route`, `strategy` |
| `rag_canary_legacy_wins_total` | `stage`, `route`, `strategy` |
| `rag_canary_equivalent_total` | `stage`, `route`, `strategy` |
| `rag_canary_inconclusive_total` | `stage`, `route`, `strategy` |
| `rag_canary_latency_delta_seconds` | `stage`, `route`, `strategy` |
| `rag_canary_cost_delta` | `stage`, `route`, `strategy` |
| `rag_canary_token_delta` | `stage`, `route`, `strategy` |
| `rag_legacy_invocations_total` | `reason` |
| `rag_shadow_*` | shadow paired evaluation |

Monitor during rollout:

- Traffic split (legacy / canonical / shadow)
- Error and fallback rates
- Quality deltas (faithfulness, correctness, relevance)
- Citation correctness and completeness
- p50/p95 latency delta
- Cost and token delta per request
- Security events (injection blocks, RBAC violations, SSRF blocks)

## Cache separation

Legacy and canonical responses use separate cache namespaces:

- `pipeline_version=legacy`
- `pipeline_version=canonical-v1`

A canonical canary answer cannot become a legacy cache hit.

## Verification policy during canary

| Verification outcome | Behavior (when legacy runtime disabled) |
|---------------------|------------------------------------------|
| `PASS` | Canonical answer returned |
| `WARN` | Abstention or caveat unless `CANARY_ALLOW_WARN_RESPONSES=true` |
| `FAIL` | Safe abstention (no legacy graph replay) |

## Staging checklist

Before user-visible canary:

1. `GET /ops/preflight?for_canary=true` — all critical checks pass
2. Shadow enabled with Redis available
3. ≥30 paired shadow records collected
4. Shadow evidence gates pass
5. OTEL optional (`OTEL_ENABLED=true`)
6. Run full test suite including `tests/test_canary_rollout.py`

## Legacy retirement

**Status: complete (Phase 7).** Legacy graph modules were removed. Retirement criteria are tracked in [LEGACY_RETIREMENT_INVENTORY.md](./LEGACY_RETIREMENT_INVENTORY.md).

- `LEGACY_RUNTIME_ENABLED=false` (default) — no legacy graph execution
- `LEGACY_FALLBACK_ENABLED=false` (default) — safe abstention on canonical failure
- Ops endpoint: `GET /ops/legacy/retirement` for retirement status
