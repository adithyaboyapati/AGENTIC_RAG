"""Tests for unified runner guardrail integration."""

from unittest.mock import patch

import pytest

from src.privacy import PrivacyMode, PrivacyPolicy
from src.runner import _prepare_agent_run, run_agent


def test_runner_rejects_short_input():
    with pytest.raises(ValueError, match="validation failed"):
        run_agent("ab", "baseline")


def test_runner_redacts_pii_and_continues():
    """Default policy is redact — the question proceeds with PII masked."""
    pre = _prepare_agent_run(
        "Contact me at user@example.com about RAG", "baseline", None, False
    )
    assert "user@example.com" not in pre.sanitized_question
    assert "[EMAIL]" in pre.sanitized_question
    # Cache is keyed on the sanitized question, never the raw one.
    assert pre.effective_question == pre.sanitized_question


def test_runner_rejects_pii_in_block_mode():
    blocking = PrivacyPolicy(input_mode=PrivacyMode.BLOCK)
    with patch("src.runner.get_privacy_policy", return_value=blocking):
        with pytest.raises(ValueError, match="sensitive data"):
            run_agent("Contact me at user@example.com", "baseline")


def test_runner_rejects_unknown_mode():
    with pytest.raises(ValueError, match="Unknown mode"):
        run_agent("What is RAG?", "invalid_mode")


def test_memory_augmentation_uses_sanitized_question():
    history = [{"role": "user", "content": "What is RAG?"}]
    pre = _prepare_agent_run(
        "Email results to a@b.com please", "baseline", history, True
    )
    assert "a@b.com" not in pre.effective_question
    assert "What is RAG?" in pre.effective_question


def test_runner_blocks_output_safety_errors():
    from src.guardrails import GuardrailViolation
    from src.schemas import AgentResponse

    err = GuardrailViolation(
        rule="markdown_image_exfil",
        message="blocked exfil",
        severity="error",
        value="x",
        limit="N/A",
    )
    fake = AgentResponse(answer="ok enough text", mode="baseline", sources=["s"])
    with patch("src.runner._run_with_cost_tracking", return_value=fake):
        with patch(
            "src.guardrails.OutputGuardrails.validate",
            return_value=(False, [err]),
        ):
            with pytest.raises(ValueError, match="safety checks"):
                run_agent("What is retrieval-augmented generation?", "baseline", use_memory=False)


def test_quality_failure_skips_cache(monkeypatch):
    from src.schemas import AgentResponse

    monkeypatch.setattr("src.cache.redis_cache.settings.cache_enabled", True)
    monkeypatch.setattr("src.config.settings.quality_guardrails_enabled", True)

    fake_resp = AgentResponse(
        answer="Ungrounded claim about RAG.",
        mode="baseline",
        sources=["rag.pdf"],
        context_docs=["RAG retrieves then generates."],
    )
    monkeypatch.setattr("src.runner._run_with_cost_tracking", lambda *a, **k: fake_resp)
    monkeypatch.setattr("src.runner._attach_follow_ups", lambda *a, **k: [])
    monkeypatch.setattr(
        "src.evaluation.metrics.evaluate_metrics",
        lambda *a, **k: type(
            "M",
            (),
            {"faithfulness": 0.1, "answer_relevance": 1.0, "context_precision": 1.0},
        )(),
    )
    cached = []
    monkeypatch.setattr(
        "src.cache.redis_cache.set_cached_response",
        lambda *a, **k: cached.append(True),
    )
    monkeypatch.setattr("src.cache.redis_cache.get_cached_response", lambda *a, **k: None)

    result = run_agent(
        "What is retrieval-augmented generation?", "baseline", use_memory=False
    )
    assert cached == []
    assert "incompletely grounded" in result.answer

