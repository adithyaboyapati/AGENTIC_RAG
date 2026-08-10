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
