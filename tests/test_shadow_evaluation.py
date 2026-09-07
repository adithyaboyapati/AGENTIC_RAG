"""Tests for Phase 5 shadow evaluation, sampling, isolation, and fallback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.config import settings
from src.evaluation.cutover_engine import CutoverRecommendation, evaluate_cutover_gates
from src.evaluation.shadow_comparison import (
    classify_disagreement,
    compare_pipelines,
    metrics_from_legacy,
)
from src.evaluation.shadow_context import is_observational_execution, shadow_execution
from src.evaluation.shadow_fingerprint import (
    build_shadow_request_context,
    compute_input_fingerprint,
)
from src.evaluation.shadow_models import ComparisonStatus, ExecutionMode, PipelineMetrics
from src.evaluation.shadow_runner import run_paired_evaluation, try_canonical_with_fallback
from src.evaluation.shadow_sampling import SamplingDecision, evaluate_sampling
from src.evaluation.shadow_storage import list_shadow_results, reset_shadow_store_for_tests
from src.evaluation.traffic_policy import execute_with_traffic_policy
from src.schemas import AgentResponse, RBACContext


@pytest.fixture(autouse=True)
def _reset_shadow_db():
    reset_shadow_store_for_tests()
    yield
    reset_shadow_store_for_tests()


@pytest.fixture
def rbac_default():
    return RBACContext(tenant_id="tenant_a", user_roles=["public"])


class TestFingerprintAndSampling:
    def test_fingerprint_is_deterministic(self, rbac_default):
        ctx = build_shadow_request_context(
            question="What is RAG?",
            legacy_mode="baseline",
            rbac_context=rbac_default,
        )
        assert compute_input_fingerprint(ctx) == compute_input_fingerprint(ctx)

    def test_sampling_is_deterministic(self, rbac_default):
        ctx = build_shadow_request_context(
            question="What is RAG?",
            legacy_mode="baseline",
            rbac_context=rbac_default,
        )
        fp = compute_input_fingerprint(ctx)
        first = evaluate_sampling(ctx, input_fingerprint=fp)
        second = evaluate_sampling(ctx, input_fingerprint=fp)
        assert first.sampling_decision == second.sampling_decision

    def test_sampling_respects_rate(self, rbac_default, monkeypatch):
        monkeypatch.setattr(settings, "shadow_enabled", True)
        monkeypatch.setattr(settings, "shadow_sampling_rate", 1.0)
        ctx = build_shadow_request_context(
            question="Sample me",
            legacy_mode="baseline",
            rbac_context=rbac_default,
        )
        outcome = evaluate_sampling(ctx)
        assert outcome.sampling_decision == SamplingDecision.SHADOW


class TestComparison:
    def test_inconclusive_when_quality_unknown(self):
        legacy = PipelineMetrics(pipeline="legacy", evidence_count=2)
        canonical = PipelineMetrics(pipeline="canonical", evidence_count=4)
        status, _, _, winner = compare_pipelines(
            legacy_metrics=legacy, canonical_metrics=canonical
        )
        assert status == ComparisonStatus.INCONCLUSIVE
        assert winner is None

    def test_disagreement_abstention(self):
        legacy = PipelineMetrics(pipeline="legacy", abstained=False, answer_length=100)
        canonical = PipelineMetrics(pipeline="canonical", abstained=True)
        assert (
            classify_disagreement(legacy, canonical).value
            == "canonical_abstained_legacy_answered"
        )


class TestPairedExecution:
    def test_paired_preserves_tenant(self, rbac_default, monkeypatch):
        monkeypatch.setattr(
            "src.evaluation.shadow_runner.run_legacy_pipeline",
            lambda *a, **k: (
                AgentResponse(answer="legacy answer here", mode="baseline"),
                {"latency_ms": 10.0},
            ),
        )
        canonical_mock = MagicMock(
            answer="canonical answer here",
            mode="canonical",
            route="retrieve",
            strategy="simple",
            evidence=(),
            citations=(),
            verification=None,
            trace=(),
            latency_ms=12.0,
            response_status="answered",
            error_code=None,
        )
        monkeypatch.setattr(
            "src.evaluation.shadow_runner.run_canonical_pipeline",
            lambda *a, **k: (canonical_mock, {"latency_ms": 12.0}),
        )
        result = run_paired_evaluation(
            question="What is RAG?",
            legacy_mode="baseline",
            rbac_context=rbac_default,
            execution_mode=ExecutionMode.REPLAY,
            persist=True,
        )
        assert result.tenant_id == "tenant_a"
        assert result.input_fingerprint
        stored = list_shadow_results(limit=1)
        assert stored
        assert stored[0]["tenant_id"] == "tenant_a"

    def test_cross_tenant_context_preserved(self):
        tenant_a = RBACContext(tenant_id="tenant_a", user_roles=["tenant_a"])
        tenant_b = RBACContext(tenant_id="tenant_b", user_roles=["tenant_b"])
        fp_a = compute_input_fingerprint(
            build_shadow_request_context(
                question="secret",
                legacy_mode="baseline",
                rbac_context=tenant_a,
            )
        )
        fp_b = compute_input_fingerprint(
            build_shadow_request_context(
                question="secret",
                legacy_mode="baseline",
                rbac_context=tenant_b,
            )
        )
        assert fp_a != fp_b


class TestIsolation:
    def test_shadow_context_blocks_cache(self):
        with shadow_execution():
            assert is_observational_execution() is True
        assert is_observational_execution() is False

    def test_shadow_does_not_write_production_cache(self, monkeypatch):
        monkeypatch.setattr(settings, "cache_enabled", True)
        client_calls: list[str] = []
        fake_client = MagicMock()
        fake_client.set = lambda *a, **k: client_calls.append("set") or True
        fake_client.get = lambda *a, **k: None
        monkeypatch.setattr("src.cache.redis_cache.get_redis_client", lambda: fake_client)
        with shadow_execution():
            from src.cache.redis_cache import set_cached_response

            set_cached_response(
                "q",
                "baseline",
                AgentResponse(answer="a", mode="baseline"),
            )
        assert client_calls == []


class TestTrafficPolicy:
    def test_legacy_authoritative_when_shadow_disabled(self, rbac_default, monkeypatch):
        monkeypatch.setattr(settings, "shadow_enabled", False)
        monkeypatch.setattr(settings, "canary_enabled", False)
        monkeypatch.setattr(
            "src.evaluation.traffic_policy.run_legacy_pipeline",
            lambda *a, **k: (
                AgentResponse(answer="legacy wins", mode="baseline"),
                {"latency_ms": 1.0},
            ),
        )
        outcome = execute_with_traffic_policy(
            question="Q",
            mode="baseline",
            rbac_context=rbac_default,
            request_id="req-1",
        )
        assert outcome.response.answer == "legacy wins"
        assert outcome.shadow_scheduled is False

    def test_shadow_scheduled_async(self, rbac_default, monkeypatch):
        monkeypatch.setattr(settings, "shadow_enabled", True)
        monkeypatch.setattr(settings, "shadow_sampling_rate", 1.0)
        monkeypatch.setattr(settings, "canary_enabled", False)
        monkeypatch.setattr(
            "src.evaluation.traffic_policy.run_legacy_pipeline",
            lambda *a, **k: (
                AgentResponse(answer="legacy", mode="baseline"),
                {"latency_ms": 1.0},
            ),
        )
        scheduled: list[str] = []
        monkeypatch.setattr(
            "src.evaluation.traffic_policy.schedule_shadow_evaluation",
            lambda **kwargs: scheduled.append(kwargs["request_id"]),
        )
        outcome = execute_with_traffic_policy(
            question="Q",
            mode="baseline",
            rbac_context=rbac_default,
            request_id="req-shadow",
        )
        assert outcome.response.answer == "legacy"
        assert outcome.shadow_scheduled is True
        assert scheduled == ["req-shadow"]


class TestFallback:
    def test_canary_falls_back_to_legacy(self, rbac_default, monkeypatch):
        monkeypatch.setattr(settings, "legacy_fallback_enabled", False)
        monkeypatch.setattr(settings, "legacy_runtime_enabled", False)
        monkeypatch.setattr(
            "src.evaluation.shadow_runner.run_canonical_pipeline",
            lambda *a, **k: (_ for _ in ()).throw(TimeoutError("canonical timeout")),
        )
        response, shadow, reason = try_canonical_with_fallback(
            question="Q",
            legacy_mode="agentic",
            rbac_context=rbac_default,
            request_id="canary-1",
        )
        assert response.error_code is not None
        assert reason is not None
        assert shadow is not None
        assert shadow.fallback_reason is not None


class TestCutoverEngine:
    def test_not_ready_without_samples(self):
        decision = evaluate_cutover_gates({"sample_count": 0, "overall": {}})
        assert decision.recommendation == CutoverRecommendation.NOT_READY
        assert decision.blockers


class TestMetricsExtraction:
    def test_legacy_metrics_from_response(self):
        metrics = metrics_from_legacy(
            AgentResponse(answer="hello world", mode="baseline", sources=["doc1"]),
            latency_ms=15.0,
        )
        assert metrics.pipeline == "legacy"
        assert metrics.latency_ms == 15.0
        assert metrics.evidence_count == 1
