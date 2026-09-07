# Evaluation (Current)

**Status: CURRENT** — describes `src/evaluation/` as implemented after Phase 8.

> Historical note: [archive/EVALUATION_REPORT.md](./archive/EVALUATION_REPORT.md) and references to "8 modes" in older docs are **historical**.

## Overview

```text
Production traffic → observations + feedback
        ↓
Versioned dataset (candidates → reviewed → golden/regression)
        ↓
Automated evaluation + regression gates
        ↓
Shadow / canary / experiments → production
```

Canonical doc for continuous eval: [PHASE8_CONTINUOUS_EVAL.md](./PHASE8_CONTINUOUS_EVAL.md).

## Retrieval evaluation

| Metric | Ground truth? | How |
|--------|---------------|-----|
| Recall@k | Partial | `retrieval_metrics.py` vs `data/eval/golden_qa.json` |
| MRR | Partial | Same golden set (keywords or `expected_chunk_ids`) |
| Hit rate | Partial | Same |
| NDCG | Not yet measured | — |
| Production proxy | **Proxy only** | Zero-evidence rate, citation count in observations |

```bash
# CI — no embeddings
python -m src.evaluation.retrieval_metrics --offline

# Live gate (nightly / manual)
python -m src.evaluation.retrieval_metrics --gate

# CI regression gates
python -m src.evaluation.eval_gates
```

## Answer evaluation

| Metric | Status |
|--------|--------|
| Faithfulness | Proxy via verification pass rate; offline via `metrics.py` (RAGAS-inspired) |
| Relevance | Same |
| Correctness | Golden Q&A keywords only where defined |
| Citation correctness | Feedback categories + manual review |
| Abstention | `response_status` in observations |

**Not yet measured:** live faithfulness/correctness at scale with human labels. Do not treat proxy metrics as ground truth.

```bash
# Optional offline LLM-judge (costs API calls)
python -m src.evaluation.metrics  # via evaluate_all_modes or comparative harness
```

## Agentic evaluation

Tracked in Phase 8 (`strategy_analytics.py`, `agentic_efficiency.py`):

- Strategy distribution (simple / decompose / multi_hop)
- `unnecessary_strategy_llm_rate`
- `ineffective_retry_rate`
- `unnecessary_multihop_rate`

## Operational evaluation

| Metric | Source |
|--------|--------|
| p50 / p95 latency | Observations + Prometheus |
| Token usage / cost | `cost_attribution.py`, Prometheus |
| Error rate | Observations, `/metrics` |
| Cache hit rate | Prometheus `rag_cache_events_total` |

## Shadow / canary

| Component | Module |
|-----------|--------|
| Paired evaluation | `shadow_runner.py` |
| Storage | `shadow_storage.py` (SQLite) |
| Gates | `canary_gates.py` |
| Traffic policy | `traffic_policy.py` |
| Dashboard | `canary_dashboard.py` |

See [CANARY_ROLLOUT.md](./CANARY_ROLLOUT.md).

**Current defaults:** shadow and canary **disabled**; canonical is primary; legacy runtime **removed**; fallback is **safe abstention**.

## Comparative evaluation

`comparative_eval.py` runs **canonical pipeline variants** (not legacy graphs):

- `canonical-simple`, `canonical-decompose`, `canonical-multi-hop`, `canonical-auto`

## Feedback → regression

1. User submits `POST /feedback` (thumbs down)
2. `feedback_classifier.py` maps to failure category
3. `regression_pipeline.py` creates sanitized **candidate** (requires review)
4. Operator promotes via dataset store or `golden_qa.json`

```bash
python -m src.feedback.export   # triage queue → data/eval/feedback_regressions.json
```

## Operator endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /ops/quality/dashboard` | Full quality dashboard |
| `GET /ops/eval/runs` | Historical eval runs |
| `POST /ops/eval/run` | Trigger evaluation |
| `GET /ops/drift` | Drift detection |

## Reproducibility

Every eval run records (`versioning.py`):

- `dataset_version`, `pipeline_version`, `model_version`, `prompt_version`, `retrieval_config_version`, `evaluation_timestamp`

Historical runs are **append-only** in `data/eval/dataset.db`.

## Test suite

The repository maintains an extensive automated test suite covering contracts, canonical graph, retrieval, security, shadow/canary, and Phase 8 continuous eval.

```bash
pytest tests/test_phase8_continuous_eval.py -q
pytest tests/test_documentation_consistency.py -q
```

Do not rely on hardcoded test counts in documentation — run `pytest --collect-only` locally.
