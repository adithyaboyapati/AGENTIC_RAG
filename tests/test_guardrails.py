"""Tests for input/output guardrails and rate limiting."""

from src.guardrails import CostGuardrails, InputGuardrails, OutputGuardrails


def test_input_rejects_too_short():
    valid, violations = InputGuardrails.validate("ab")
    assert not valid
    assert any(v.rule == "min_length" for v in violations)


def test_input_rejects_credential_material():
    valid, violations = InputGuardrails.validate(
        "Use api_key=sk-abcdefghijklmnop1234 to call the service"
    )
    assert not valid
    assert any(v.rule == "blocked_keyword" for v in violations)


def test_input_rejects_openai_key():
    valid, violations = InputGuardrails.validate(
        "My key is sk-proj-abcdefghijklmnopqrstuvwx, is it valid?"
    )
    assert not valid


def test_input_accepts_valid_question():
    valid, violations = InputGuardrails.validate("What is retrieval-augmented generation?")
    assert valid
    assert violations == []


def test_input_accepts_questions_about_tokens_and_secrets():
    """Words like 'token' or 'secret' must not be blocked — only credential material."""
    for q in [
        "What is a token limit in LLMs?",
        "How do secret management systems work?",
        "Explain API key rotation best practices",
    ]:
        valid, violations = InputGuardrails.validate(q)
        assert valid, f"False positive on: {q} — {violations}"


def test_output_warns_on_no_sources():
    valid, violations = OutputGuardrails.validate("Short answer here.", sources=[])
    assert any(v.rule == "no_sources" for v in violations)
    assert any(v.severity == "warning" for v in violations)


def test_rate_limit_blocks_excess_queries():
    tracker = CostGuardrails()
    from src.config import settings

    original = settings.max_queries_per_minute
    settings.max_queries_per_minute = 2
    try:
        assert tracker.check_query_rate()[0]
        tracker.record_query()
        assert tracker.check_query_rate()[0]
        tracker.record_query()
        ok, violations = tracker.check_query_rate()
        assert not ok
        assert violations[0].rule == "queries_per_minute"
    finally:
        settings.max_queries_per_minute = original


def test_token_budget_blocks_when_exhausted():
    tracker = CostGuardrails()
    from src.config import settings

    original = settings.max_tokens_per_minute
    settings.max_tokens_per_minute = 100
    try:
        assert tracker.check_token_budget()[0]
        tracker.record_usage(input_tokens=80, output_tokens=40)
        ok, violations = tracker.check_token_budget()
        assert not ok
        assert any(v.rule == "tokens_per_minute" for v in violations)
    finally:
        settings.max_tokens_per_minute = original
