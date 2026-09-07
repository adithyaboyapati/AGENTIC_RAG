"""Phase 8 continuous evaluation, regression, and optimization tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.evaluation.agentic_efficiency import build_agentic_efficiency_report
from src.evaluation.continuous_eval import run_scheduled_evaluation
from src.evaluation.cost_attribution import build_cost_attribution
from src.evaluation.dataset_store import EvalCase, append_eval_run, list_cases, save_case
from src.evaluation.eval_gates import run_eval_gates
from src.evaluation.experiments import Experiment, assign_experiment_bucket, save_experiment
from src.evaluation.feedback_classifier import classify_feedback
from src.evaluation.model_routing import ModelTask, route_model
from src.evaluation.production_observer import ProductionObservation, record_observation
from src.evaluation.regression_pipeline import create_regression_candidate_from_feedback
from src.evaluation.retrieval_metrics import validate_golden_set_offline
from src.evaluation.versioning import current_eval_manifest, current_prompt_version
from src.ingestion.document_registry import document_freshness, register_document_ingest


@pytest.fixture(autouse=True)
def isolated_eval_dbs(monkeypatch, tmp_path):
    monkeypatch.setattr("src.config.settings.eval_dataset_db_path", str(tmp_path / "dataset.db"))
    monkeypatch.setattr(
        "src.config.settings.production_observations_db_path", str(tmp_path / "observations.db")
    )
    monkeypatch.setattr("src.config.settings.experiments_db_path", str(tmp_path / "experiments.db"))
    monkeypatch.setattr(
        "src.config.settings.document_registry_db_path", str(tmp_path / "document_registry.db")
    )
    monkeypatch.setattr("src.config.settings.continuous_eval_enabled", True)


def test_version_manifest_is_reproducible():
    m1 = current_eval_manifest()
    m2 = current_eval_manifest()
    assert m1.pipeline_version == m2.pipeline_version
    assert m1.prompt_version == current_prompt_version()
    assert m1.model_version.startswith("model-")


def test_dataset_lifecycle_and_eval_run_append_only():
    case = EvalCase(question="What is RAG?", status="candidate", failure_category="unknown")
    save_case(case)
    rows = list_cases(status="candidate")
    assert len(rows) == 1
    manifest = current_eval_manifest().to_dict()
    run_id = append_eval_run(trigger="test", manifest=manifest, summary={"ok": True})
    assert run_id


def test_feedback_classifier_maps_hallucination():
    result = classify_feedback(
        {"rating": "down", "categories": ["hallucination"], "comment": ""}
    )
    assert result.failure_category == "hallucination"
    assert result.requires_review is True


def test_regression_candidate_from_feedback():
    record = {
        "id": "fb1",
        "rating": "down",
        "question": "What is CRAG?",
        "answer": "Wrong answer",
        "categories": ["wrong_source"],
        "tenant_id": "default",
    }
    case = create_regression_candidate_from_feedback(record)
    assert case is not None
    assert case.failure_category == "citation_failure"
    assert list_cases(status="candidate")


def test_production_observation_and_cost_attribution():
    obs = ProductionObservation(
        request_id="req-1",
        tenant_id="default",
        route="retrieve",
        strategy="simple",
        strategy_decision_source="heuristic",
        verification_status="pass",
        response_status="ok",
        evidence_count=3,
        citation_count=2,
        retry_count=0,
        llm_call_count=2,
        latency_ms=120.0,
        cost_usd=0.001,
        input_tokens=100,
        output_tokens=50,
        model_id="gpt-test",
        pipeline_version="canonical-v1",
    )
    record_observation(obs)
    cost = build_cost_attribution(window_hours=1.0)
    assert cost.total_requests >= 1
    assert cost.cost_per_request > 0


def test_experiment_deterministic_assignment():
    exp = Experiment(name="prompt-test", traffic_percent=50.0, status="running")
    save_experiment(exp)
    a = assign_experiment_bucket(
        experiment_id=exp.experiment_id, request_id="req-a", traffic_percent=50.0
    )
    b = assign_experiment_bucket(
        experiment_id=exp.experiment_id, request_id="req-a", traffic_percent=50.0
    )
    assert a == b
    assert a in {"control", "treatment"}


def test_model_routing_policy():
    decision = route_model(ModelTask.SIMPLE, complexity="simple")
    assert decision.model_id
    assert decision.task == "simple"


def test_eval_gates_offline():
    offline = validate_golden_set_offline()
    report = run_eval_gates(offline_summary=offline)
    assert report.overall_status in {"pass", "fail_high", "fail_critical"}


def test_scheduled_evaluation_runs():
    result = run_scheduled_evaluation()
    assert result.run_id
    assert result.manifest["pipeline_version"].startswith("canonical-")


def test_document_registry_and_freshness():
    register_document_ingest(source="/data/test.pdf", filename="test.pdf", chunk_count=12)
    fresh = document_freshness("/data/test.pdf")
    assert fresh["freshness"] in {"fresh", "aging", "stale", "unknown"}
    assert fresh.get("chunk_count") == 12


def test_agentic_efficiency_report_empty_window():
    report = build_agentic_efficiency_report(window_hours=0.001)
    assert report.sample_count >= 0


def test_end_to_end_improvement_loop():
    """Production failure → feedback → regression candidate → eval run."""
    feedback = {
        "id": "fb-e2e",
        "rating": "down",
        "question": "Compare RAG and Agentic RAG",
        "answer": "Unsupported claim",
        "categories": ["hallucination"],
        "comment": "Made up a comparison",
        "request_id": "req-e2e",
    }
    case = create_regression_candidate_from_feedback(feedback)
    assert case is not None
    eval_result = run_scheduled_evaluation()
    assert eval_result.regression_candidates >= 1
    assert eval_result.gate_report.overall_status
