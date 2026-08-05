"""Tests for unified runner guardrail integration."""

import pytest

from src.runner import run_agent


def test_runner_rejects_short_input():
    with pytest.raises(ValueError, match="validation failed"):
        run_agent("ab", "baseline")


def test_runner_rejects_pii():
    with pytest.raises(ValueError, match="sensitive data"):
        run_agent("Contact me at user@example.com", "baseline")


def test_runner_rejects_unknown_mode():
    with pytest.raises(ValueError, match="Unknown mode"):
        run_agent("What is RAG?", "invalid_mode")
