"""Tests for conversation memory."""

from src.memory.chat_memory import (
    augment_question_with_history,
    format_chat_history,
    pair_exchanges,
)


def test_format_empty_history():
    assert format_chat_history([]) == ""


def test_pair_exchanges():
    messages = [
        {"role": "user", "content": "What is RAG?"},
        {"role": "assistant", "content": "RAG retrieves then generates."},
        {"role": "user", "content": "And CRAG?"},
        {"role": "assistant", "content": "CRAG grades docs."},
    ]
    pairs = pair_exchanges(messages)
    assert pairs == [
        ("What is RAG?", "RAG retrieves then generates."),
        ("And CRAG?", "CRAG grades docs."),
    ]


def test_format_recent_includes_truncated_answers():
    long_answer = "A" * 600
    messages = [
        {"role": "user", "content": "What is Self-RAG?"},
        {"role": "assistant", "content": long_answer},
    ]
    text = format_chat_history(
        messages,
        recent_exchanges=3,
        answer_max_chars=500,
    )
    assert "Recent exchanges" in text
    assert "Q1: What is Self-RAG?" in text
    assert "A1:" in text
    assert len([line for line in text.splitlines() if line.startswith("A1:")][0]) <= 506
    assert "…" in text


def test_format_older_queries_only():
    messages = []
    for i in range(5):
        messages.append({"role": "user", "content": f"Question {i}"})
        messages.append({"role": "assistant", "content": f"Answer {i} " + ("x" * 200)})

    text = format_chat_history(
        messages,
        recent_exchanges=3,
        answer_max_chars=500,
        max_older_queries=10,
    )
    assert "Earlier questions" in text
    assert "1. Question 0" in text
    assert "2. Question 1" in text
    # Older answers should not appear in the topic trail section
    older_section = text.split("Recent exchanges")[0]
    assert "Answer 0" not in older_section
    assert "Answer 1" not in older_section
    # Recent answers are present (truncated)
    assert "Q1: Question 2" in text or "Q1: Question" in text
    assert "Recent exchanges" in text
    assert "A1:" in text


def test_augment_question_with_history():
    messages = [
        {"role": "user", "content": "What is CRAG?"},
        {"role": "assistant", "content": "CRAG grades retrieved documents."},
    ]
    augmented = augment_question_with_history(
        "Explain more about the grading step",
        messages,
        recent_exchanges=3,
        answer_max_chars=500,
    )
    assert "Previous conversation:" in augmented
    assert "Explain more about the grading step" in augmented
    assert "CRAG grades" in augmented
    assert "Q1: What is CRAG?" in augmented


def test_augment_without_history_returns_original():
    q = "What is Self-RAG?"
    assert augment_question_with_history(q, []) == q
