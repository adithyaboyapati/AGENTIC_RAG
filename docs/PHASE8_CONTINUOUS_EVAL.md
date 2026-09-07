# Phase 8 — Continuous Evaluation & Productization

Phase 8 turns the canonical Agentic RAG system into a **continuously evaluated, measurable, optimizable platform** without changing the canonical graph topology.

## Continuous evaluation loop

```text
Production Traffic → Observability → Feedback / Failure Detection
        ↓
Evaluation Dataset (versioned) → Automated Evaluation → Regression Detection
        ↓
Experiment → Shadow → Canary → Production
```

## Key modules

| Module | Purpose |
|--------|---------|
| `src/evaluation/versioning.py` | Reproducible eval manifests (dataset/pipeline/model/prompt/retrieval) |
| `src/evaluation/dataset_store.py` | Versioned eval case lifecycle + append-only eval runs |
| `src/evaluation/regression_pipeline.py` | Production failures → sanitized regression candidates |
| `src/evaluation/feedback_classifier.py` | User feedback → failure categories |
| `src/evaluation/production_observer.py` | Per-request production observations |
| `src/evaluation/continuous_eval.py` | Scheduled + failure-driven evaluation |
| `src/evaluation/eval_gates.py` | CI regression gates (critical/high/medium/informational) |
| `src/evaluation/quality_dashboard.py` | Operator quality dashboard |
| `src/evaluation/strategy_analytics.py` | Strategy effectiveness metrics |
| `src/evaluation/agentic_efficiency.py` | Unnecessary agentic work detection |
| `src/evaluation/model_routing.py` | Policy-based model selection abstraction |
| `src/evaluation/cost_attribution.py` | Cost per request/strategy/model/tenant |
| `src/evaluation/experiments.py` | Lightweight A/B experiments on canary infra |
| `src/evaluation/drift_detection.py` | Quality drift monitoring |
| `src/evaluation/retrieval_monitoring.py` | Retrieval proxy metrics (explicitly labeled) |
| `src/evaluation/retrieval_drift.py` | Retrieval drift warnings |
| `src/evaluation/kb_monitoring.py` | Corpus quality monitoring |
| `src/ingestion/document_registry.py` | Document versioning + freshness |

## Operator endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /ops/quality/dashboard` | Full production quality dashboard |
| `GET /ops/eval/runs` | Historical evaluation runs |
| `GET /ops/eval/cases` | Regression/golden case queue |
| `POST /ops/eval/run` | Trigger scheduled or failure-driven eval |
| `GET /ops/drift` | Quality + retrieval drift report |
| `GET /ops/experiments` | Experiment registry |
| `GET /ops/documents/freshness?source=` | Document freshness metadata |

## CLI

```bash
python -m src.evaluation.eval_gates              # CI regression gate
python -m src.evaluation.continuous_eval_cli     # scheduled eval
python -m src.feedback.export                    # export negative feedback queue
```

## Product API fields

`POST /query` responses expose user-visible quality signals:

- `answer`, `citations`, `verification_status`, `confidence`, `response_status`
- `pipeline_version`, `request_id` (for feedback correlation)

Internal chain-of-thought and raw prompts are **not** exposed.

## Invariants preserved

- One canonical production graph (v1)
- Historical eval results are append-only
- Regression candidates require human review before golden promotion
- Proxy metrics are labeled as proxies
- Canary remains the deployment safety mechanism
