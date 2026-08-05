"""Tests for conversation memory."""

from src.memory.chat_memory import augment_question_with_history, format_chat_history


def test_format_empty_history():
    assert format_chat_history([]) == ""


def test_format_chat_history():
    messages = [
        {"role": "user", "content": "What is RAG?"},
        {"role": "assistant", "content": "RAG combines retrieval with generation."},
    ]
    text = format_chat_history(messages)
    assert "User: What is RAG?" in text
    assert "Assistant: RAG combines" in text


def test_augment_question_with_history():
    messages = [
        {"role": "user", "content": "What is CRAG?"},
        {"role": "assistant", "content": "CRAG grades retrieved documents."},
    ]
    augmented = augment_question_with_history("Explain more about the grading step", messages)
    assert "Previous conversation:" in augmented
    assert "Explain more about the grading step" in augmented
    assert "CRAG grades" in augmented


def test_augment_without_history_returns_original():
    q = "What is Self-RAG?"
    assert augment_question_with_history(q, []) == q
