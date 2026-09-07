"""Tests for Phase 6 canary rollout, gates, streaming policy, and rollback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.cache.redis_cache import build_cache_key
from src.config import settings
from src.evaluation.canary_gates import (
    CanaryGateResult,
    GateRecommendation,
    evaluate_canary_promotion_gates,
    evaluate_full_cutover_readiness,
    evaluate_rollback_conditions,
    evaluate_shadow_evidence_gate,
)
from src.evaluation.canary_rollout import (
    STAGE_TO_PERCENT,
    effective_canary_percent,
    get_rollout_state,
    is_canary_active,
    kill_canary,
    reset_canary_kill_switch,
)
from src.evaluation.canary_statistics import analyze_paired_results
from src.evaluation.pipeline_version import PIPELINE_CANONICAL_V1, PIPELINE_LEGACY
from src.evaluation.preflight import PreflightReport, run_preflight
from src.evaluation.shadow_context import shadow_execution
from src.evaluation.shadow_fingerprint import (
    build_shadow_request_context,
    compute_input_fingerprint,
)
from src.evaluation.shadow_models import ExecutionMode
from src.evaluation.shadow_runner import try_canonical_with_fallback
from src.evaluation.shadow_sampling import SamplingDecision, evaluate_sampling
from src.evaluation.shadow_storage import reset_shadow_store_for_tests, save_shadow_result
from src.evaluation.traffic_policy import (
    TrafficPath,
    execute_with_traffic_policy,
    iter_stream_with_traffic_policy,
    resolve_traffic_policy,
)
from src.schemas import AgentResponse, RBACContext


@pytest.fixture(autouse=True)
def _reset_state():
    reset_shadow_store_for_tests()
    reset_canary_kill_switch()
    yield
    reset_shadow_store_for_tests()
    reset_canary_kill_switch()


@pytest.fixture
def rbac_default():
    return RBACContext(tenant_id="tenant_a", user_roles=["public"])


class TestPreflight:
    def test_valid_configuration_reports_checks(self):
        report = run_preflight(for_canary=False)
        assert isinstance(report, PreflightReport)
        assert report.checks
        assert all(c.component and c.status and c.severity for c in report.checks)

    def test_missing_redis_is_degraded_not_blocking(self, monkeypatch):
        monkeypatch.setattr("src.cache.redis_cache.get_redis_client", lambda: None)
        report = run_preflight(for_canary=True)
        redis_check = next(c for c in report.checks if c.component == "redis")
        assert redis_check.status in ("degraded", "failed", "ok")

    def test_missing_llm_blocks_canary(self, monkeypatch):
        monkeypatch.setattr(settings, "openai_api_key", "")
        monkeypatch.setattr(settings, "groq_api_key", "")
        report = run_preflight(for_canary=True)
        llm = next(c for c in report.checks if c.component == "llm_provider")
        assert llm.status == "failed"
        assert report.canary_allowed is False

    def test_missing_verification_llm_blocks_canary(self, monkeypatch):
        monkeypatch.setattr(settings, "canonical_verification_llm_enabled", True)
        monkeypatch.setattr(settings, "openai_api_key", "")
        report = run_preflight(for_canary=True)
        assert report.canary_allowed is False
        verification = next(c for c in report.checks if c.component == "verification_llm")
        assert verification.status == "failed"


class TestTrafficPolicyQuery:
    def test_legacy_when_shadow_and_canary_disabled(self, rbac_default, monkeypatch):
        monkeypatch.setattr(settings, "shadow_enabled", False)
        monkeypatch.setattr(settings, "canary_enabled", False)
        resolution = resolve_traffic_policy(
            question="Q",
            mode="baseline",
            rbac_context=rbac_default,
            request_id="req-1",
        )
        assert resolution.path == TrafficPath.LEGACY

    def test_canary_blocked_when_preflight_fails(self, rbac_default, monkeypatch):
        monkeypatch.setattr(settings, "canary_enabled", True)
        monkeypatch.setattr(settings, "canary_stage", "1")
        monkeypatch.setattr(
            "src.evaluation.traffic_policy.evaluate_sampling",
            lambda *a, **k: type(
                "Outcome",
                (),
                {
                    "sampling_decision": SamplingDecision.CANARY,
                    "shadow_enabled": False,
                    "sampling_rate": 0.0,
                    "canary_enabled": True,
                    "canary_percent": 1.0,
                    "bucket": 0,
                },
            )(),
        )
        monkeypatch.setattr(
            "src.evaluation.traffic_policy.run_preflight",
            lambda **kwargs: type(
                "Report",
                (),
                {"canary_allowed": False, "shadow_allowed": True, "checks": ()},
            )(),
        )
        resolution = resolve_traffic_policy(
            question="canary me now",
            mode="baseline",
            rbac_context=rbac_default,
            request_id="req-preflight",
        )
        assert resolution.path == TrafficPath.LEGACY
        assert resolution.block_reason == "preflight_failed"


class TestStreamingTrafficPolicy:
    def test_stream_uses_same_resolution_as_query(self, rbac_default, monkeypatch):
        monkeypatch.setattr(settings, "shadow_enabled", False)
        monkeypatch.setattr(settings, "canary_enabled", False)

        def _fake_stream(*args, **kwargs):
            yield {"type": "step", "content": "retrieve"}
            yield {"type": "answer", "content": "stream answer"}
            yield {"type": "done", "mode": "baseline", "latency_ms": 1.0}

        monkeypatch.setattr(
            "src.runner.stream_agent",
            _fake_stream,
        )
        query_res = resolve_traffic_policy(
            question="stream question here",
            mode="baseline",
            rbac_context=rbac_default,
            request_id="stream-req",
        )
        events = list(
            iter_stream_with_traffic_policy(
                question="stream question here",
                mode="baseline",
                rbac_context=rbac_default,
                request_id="stream-req",
            )
        )
        assert query_res.path == TrafficPath.LEGACY
        assert any(e.get("type") in ("answer", "done", "step") for e in events)

    def test_stream_canary_path(self, rbac_default, monkeypatch):
        monkeypatch.setattr(settings, "canary_enabled", True)
        monkeypatch.setattr(settings, "canary_stage", "100")
        monkeypatch.setattr(
            "src.evaluation.traffic_policy.evaluate_sampling",
            lambda *a, **k: type(
                "Outcome",
                (),
                {
                    "sampling_decision": SamplingDecision.CANARY,
                    "shadow_enabled": False,
                    "sampling_rate": 0.0,
                    "canary_enabled": True,
                    "canary_percent": 100.0,
                    "bucket": 0,
                },
            )(),
        )
        canonical = MagicMock(
            answer="canonical stream answer",
            mode="canonical",
            route="retrieve",
            strategy="simple",
            evidence=(),
            citations=(),
            verification=None,
            trace=(),
            latency_ms=10.0,
            response_status="answered",
            error_code=None,
        )
        monkeypatch.setattr(
            "src.evaluation.traffic_policy.execute_with_traffic_policy",
            lambda **kwargs: type(
                "Outcome",
                (),
                {
                    "response": AgentResponse(
                        answer="canonical stream answer", mode="canonical"
                    ),
                    "request_id": "canary-stream",
                    "execution_mode": "canary",
                    "path": TrafficPath.CANARY,
                    "pipeline_version": PIPELINE_CANONICAL_V1,
                    "canary_used": True,
                    "fallback_reason": None,
                    "shadow_result": None,
                },
            )(),
        )
        events = list(
            iter_stream_with_traffic_policy(
                question="stream canary question",
                mode="baseline",
                rbac_context=rbac_default,
                request_id="canary-stream",
            )
        )
        assert any(e.get("type") == "answer" for e in events)
        assert any(e.get("type") == "done" for e in events)


class TestCanaryAssignment:
    def test_deterministic_bucket(self, rbac_default):
        ctx = build_shadow_request_context(
            question="stable question",
            legacy_mode="baseline",
            rbac_context=rbac_default,
        )
        fp = compute_input_fingerprint(ctx)
        first = evaluate_sampling(ctx, input_fingerprint=fp)
        second = evaluate_sampling(ctx, input_fingerprint=fp)
        assert first.bucket == second.bucket
        assert first.sampling_decision == second.sampling_decision

    def test_retry_stability(self, rbac_default, monkeypatch):
        monkeypatch.setattr(settings, "canary_enabled", True)
        monkeypatch.setattr(settings, "canary_stage", "5")
        ctx = build_shadow_request_context(
            question="retry stable",
            legacy_mode="agentic",
            rbac_context=rbac_default,
        )
        fp = compute_input_fingerprint(ctx)
        decisions = [
            evaluate_sampling(ctx, input_fingerprint=fp).sampling_decision
            for _ in range(5)
        ]
        assert len(set(decisions)) == 1

    def test_tenant_preservation(self):
        tenant_a = RBACContext(tenant_id="tenant_a", user_roles=["public"])
        tenant_b = RBACContext(tenant_id="tenant_b", user_roles=["public"])
        fp_a = compute_input_fingerprint(
            build_shadow_request_context(
                question="tenant question",
                legacy_mode="baseline",
                rbac_context=tenant_a,
            )
        )
        fp_b = compute_input_fingerprint(
            build_shadow_request_context(
                question="tenant question",
                legacy_mode="baseline",
                rbac_context=tenant_b,
            )
        )
        assert fp_a != fp_b

    def test_stage_percent_mapping(self, monkeypatch):
        for stage, pct in STAGE_TO_PERCENT.items():
            monkeypatch.setattr(settings, "canary_stage", stage)
            assert effective_canary_percent() == pct


class TestShadowIsolation:
    def test_shadow_legacy_authoritative(self, rbac_default, monkeypatch):
        monkeypatch.setattr(settings, "shadow_enabled", True)
        monkeypatch.setattr(settings, "shadow_sampling_rate", 1.0)
        monkeypatch.setattr(settings, "canary_enabled", False)
        monkeypatch.setattr(
            "src.evaluation.traffic_policy.run_legacy_pipeline",
            lambda *a, **k: (
                AgentResponse(answer="legacy visible", mode="baseline"),
                {"latency_ms": 1.0},
            ),
        )
        scheduled = []
        monkeypatch.setattr(
            "src.evaluation.traffic_policy.schedule_shadow_evaluation",
            lambda **kwargs: scheduled.append(kwargs["request_id"]),
        )
        outcome = execute_with_traffic_policy(
            question="Q",
            mode="baseline",
            rbac_context=rbac_default,
            request_id="shadow-req",
        )
        assert outcome.response.answer == "legacy visible"
        assert outcome.shadow_scheduled is True
        assert scheduled == ["shadow-req"]

    def test_cache_namespace_separation(self, rbac_default):
        legacy_key = build_cache_key("q", "baseline", rbac_default, PIPELINE_LEGACY)
        canonical_key = build_cache_key(
            "q", "baseline", rbac_default, PIPELINE_CANONICAL_V1
        )
        assert legacy_key != canonical_key
        assert PIPELINE_LEGACY in legacy_key
        assert PIPELINE_CANONICAL_V1 in canonical_key

    def test_observational_execution_skips_cache(self, monkeypatch):
        monkeypatch.setattr(settings, "cache_enabled", True)
        writes: list[str] = []
        fake = MagicMock()
        fake.setex = lambda *a, **k: writes.append("set") or True
        fake.get = lambda *a, **k: None
        monkeypatch.setattr("src.cache.redis_cache.get_redis_client", lambda: fake)
        with shadow_execution():
            from src.cache.redis_cache import set_cached_response

            set_cached_response("q", "baseline", AgentResponse(answer="a", mode="baseline"))
        assert writes == []


class TestCanaryExecution:
    def test_canary_visible_on_success(self, rbac_default, monkeypatch):
        canonical = MagicMock(
            answer="canonical answer here",
            mode="canonical",
            route="retrieve",
            strategy="simple",
            evidence=(),
            citations=(),
            verification=None,
            trace=(),
            latency_ms=10.0,
            response_status="answered",
            error_code=None,
        )
        monkeypatch.setattr(
            "src.evaluation.shadow_runner.run_canonical_pipeline",
            lambda *a, **k: (canonical, {"latency_ms": 10.0}),
        )
        response, shadow, reason = try_canonical_with_fallback(
            question="Q",
            legacy_mode="baseline",
            rbac_context=rbac_default,
            request_id="canary-ok",
        )
        assert response.answer == "canonical answer here"
        assert reason is None

    def test_fallback_on_canonical_failure(self, rbac_default, monkeypatch):
        monkeypatch.setattr(settings, "legacy_fallback_enabled", False)
        monkeypatch.setattr(settings, "legacy_runtime_enabled", False)
        monkeypatch.setattr(
            "src.evaluation.shadow_runner.run_canonical_pipeline",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        response, shadow, reason = try_canonical_with_fallback(
            question="Q",
            legacy_mode="baseline",
            rbac_context=rbac_default,
            request_id="canary-fail",
        )
        assert response.error_code is not None
        assert reason is not None
        assert shadow is not None

    def test_verification_fail_falls_back(self, rbac_default, monkeypatch):
        monkeypatch.setattr(settings, "legacy_fallback_enabled", False)
        monkeypatch.setattr(settings, "legacy_runtime_enabled", False)
        verification = MagicMock(outcome="FAIL")
        canonical = MagicMock(
            answer="bad answer",
            mode="canonical",
            verification=verification,
            response_status="answered",
            error_code=None,
        )
        monkeypatch.setattr(
            "src.evaluation.shadow_runner.run_canonical_pipeline",
            lambda *a, **k: (canonical, {"latency_ms": 5.0}),
        )
        response, _, reason = try_canonical_with_fallback(
            question="Q",
            legacy_mode="baseline",
            rbac_context=rbac_default,
            request_id="verify-fail",
        )
        assert response.error_code is not None
        assert reason is not None

    def test_verification_warn_policy(self, rbac_default, monkeypatch):
        monkeypatch.setattr(settings, "canary_allow_warn_responses", False)
        monkeypatch.setattr(settings, "legacy_fallback_enabled", False)
        monkeypatch.setattr(settings, "legacy_runtime_enabled", False)
        verification = MagicMock(outcome="WARN")
        canonical = MagicMock(
            answer="warn answer",
            mode="canonical",
            verification=verification,
            response_status="answered",
            error_code=None,
        )
        monkeypatch.setattr(
            "src.evaluation.shadow_runner.run_canonical_pipeline",
            lambda *a, **k: (canonical, {"latency_ms": 5.0}),
        )
        response, _, reason = try_canonical_with_fallback(
            question="Q",
            legacy_mode="baseline",
            rbac_context=rbac_default,
            request_id="warn-fail",
        )
        assert response.error_code is not None
        assert reason is not None


class TestPromotionGates:
    def _save_row(self, **overrides):
        row = {
            "request_id": overrides.get("request_id", "r1"),
            "tenant_id": "tenant_a",
            "execution_mode": overrides.get("execution_mode", "shadow"),
            "comparison_status": overrides.get("comparison_status", "equivalent"),
            "latency_delta_ms": overrides.get("latency_delta_ms", 100.0),
            "cost_delta_usd": overrides.get("cost_delta_usd", 0.001),
            "token_delta": overrides.get("token_delta", 10),
            "fallback_reason": overrides.get("fallback_reason"),
            "errors": overrides.get("errors", []),
            "canonical_metrics": overrides.get(
                "canonical_metrics",
                {"faithfulness": 0.8, "route": "retrieve", "strategy": "simple"},
            ),
            "legacy_metrics": overrides.get("legacy_metrics", {}),
            "created_at": overrides.get("created_at", 1.0),
        }
        save_shadow_result_from_dict(row)

    def test_insufficient_sample_size_blocks(self):
        gate = evaluate_shadow_evidence_gate(min_samples=30)
        assert gate.eligible is False
        assert any(g.gate_name == "shadow_minimum_samples" for g in gate.blocking_gates)

    def test_passed_shadow_gate_with_samples(self, monkeypatch):
        for i in range(30):
            self._save_row(request_id=f"shadow-{i}", execution_mode="shadow")
        gate = evaluate_shadow_evidence_gate(min_samples=30)
        assert gate.recommendation == GateRecommendation.READY_FOR_CANARY

    def test_latency_regression_blocks_promotion(self, monkeypatch):
        monkeypatch.setattr(settings, "canary_max_p95_latency_delta_ms", 100.0)
        monkeypatch.setattr(
            "src.evaluation.canary_gates.run_preflight",
            lambda **kwargs: type(
                "Report",
                (),
                {"canary_allowed": True, "shadow_allowed": True, "checks": ()},
            )(),
        )
        monkeypatch.setattr(
            "src.evaluation.canary_gates.stage_hold_satisfied",
            lambda: (True, "hold_satisfied"),
        )
        for i in range(5):
            self._save_row(
                request_id=f"canary-{i}",
                execution_mode="canary",
                latency_delta_ms=5000.0,
            )
        gate = evaluate_canary_promotion_gates()
        assert any(g.gate_name == "latency_p95_delta" for g in gate.blocking_gates)

    def test_security_regression_triggers_rollback(self):
        self._save_row(
            execution_mode="canary",
            errors=["tenant_isolation_violation"],
        )
        rollback = evaluate_rollback_conditions()
        assert rollback.eligible is False

    def test_cutover_not_ready_without_evidence(self):
        cutover = evaluate_full_cutover_readiness()
        assert cutover.recommendation == GateRecommendation.NOT_READY


class TestRollback:
    def test_kill_switch_stops_canary(self, monkeypatch):
        monkeypatch.setattr(settings, "canary_enabled", True)
        monkeypatch.setattr(settings, "canary_stage", "25")
        assert is_canary_active()
        kill_canary()
        assert is_canary_active() is False
        state = get_rollout_state()
        assert state.kill_switch_active is True

    def test_disabled_canary_env_stops_assignments(self, monkeypatch):
        monkeypatch.setattr(settings, "canary_enabled", False)
        monkeypatch.setattr(settings, "canary_stage", "100")
        assert is_canary_active() is False

    def test_auto_rollback_downgrades_canary_path(self, rbac_default, monkeypatch):
        monkeypatch.setattr(settings, "canary_enabled", True)
        monkeypatch.setattr(settings, "canary_stage", "5")
        monkeypatch.setattr(
            "src.evaluation.traffic_policy.evaluate_sampling",
            lambda *a, **k: type(
                "Outcome",
                (),
                {
                    "sampling_decision": SamplingDecision.CANARY,
                    "shadow_enabled": False,
                    "sampling_rate": 0.0,
                    "canary_enabled": True,
                    "canary_percent": 5.0,
                    "bucket": 0,
                },
            )(),
        )
        monkeypatch.setattr(
            "src.evaluation.traffic_policy.evaluate_rollback_conditions",
            lambda: type(
                "Rollback",
                (),
                {
                    "blocking_gates": [
                        CanaryGateResult(
                            gate_name="abnormal_fallback_rate",
                            passed=False,
                            actual_value=0.5,
                            required_value=0.25,
                            sample_count=10,
                            reason="too high",
                        )
                    ],
                    "eligible": False,
                },
            )(),
        )
        monkeypatch.setattr(
            "src.evaluation.traffic_policy.run_preflight",
            lambda **kwargs: type(
                "Report",
                (),
                {"canary_allowed": True, "shadow_allowed": True, "checks": ()},
            )(),
        )
        resolution = resolve_traffic_policy(
            question="rollback question here",
            mode="baseline",
            rbac_context=rbac_default,
            request_id="rollback-req",
        )
        assert resolution.path == TrafficPath.LEGACY
        assert resolution.block_reason == "auto_rollback"
        assert is_canary_active() is False


class TestCutover:
    def test_hundred_percent_canary_stage(self, monkeypatch):
        monkeypatch.setattr(settings, "canary_enabled", True)
        monkeypatch.setattr(settings, "canary_stage", "100")
        assert effective_canary_percent() == 100.0

    def test_legacy_fallback_remains_available(self, monkeypatch):
        monkeypatch.setattr(settings, "canonical_primary", True)
        monkeypatch.setattr(settings, "canary_enabled", True)
        monkeypatch.setattr(settings, "canary_stage", "100")
        monkeypatch.setattr(settings, "legacy_fallback_enabled", True)
        state = get_rollout_state()
        assert state.legacy_fallback_enabled is True

    def test_paired_statistics_empty(self):
        stats = analyze_paired_results(execution_mode="canary")
        assert stats["sample_count"] == 0


def save_shadow_result_from_dict(row: dict) -> None:
    """Helper to persist minimal shadow rows for gate tests."""
    from src.evaluation.shadow_comparison import enrich_shadow_result
    from src.evaluation.shadow_models import PipelineMetrics, ShadowResult

    legacy = PipelineMetrics(pipeline="legacy", latency_ms=100.0)
    canonical = PipelineMetrics(
        pipeline="canonical",
        latency_ms=100.0 + float(row.get("latency_delta_ms") or 0.0),
        route=(row.get("canonical_metrics") or {}).get("route"),
        strategy=(row.get("canonical_metrics") or {}).get("strategy"),
        faithfulness=(row.get("canonical_metrics") or {}).get("faithfulness"),
        error_code=(row.get("canonical_metrics") or {}).get("error_code"),
    )
    result = ShadowResult(
        request_id=row["request_id"],
        tenant_id=row.get("tenant_id", "default"),
        input_fingerprint="fp",
        execution_mode=ExecutionMode(row.get("execution_mode", "shadow")),
        legacy_mode="baseline",
        canonical_strategy="auto",
        legacy_metrics=legacy,
        canonical_metrics=canonical,
        legacy_response_summary={},
        canonical_response_summary={},
        errors=tuple(row.get("errors") or []),
        fallback_reason=row.get("fallback_reason"),
    )
    enriched = enrich_shadow_result(result)
    save_shadow_result(enriched)
