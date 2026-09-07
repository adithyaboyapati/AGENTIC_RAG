"""Tests for the user feedback loop (store, API, export)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.config import settings
from src.feedback import store as feedback_store
from src.feedback.export import build_regression_items
from src.feedback.store import FeedbackRecord, list_feedback, save_feedback, summarize_feedback


@pytest.fixture
def sqlite_feedback(tmp_path, monkeypatch):
    """Point the store at a throwaway SQLite file and disable Supabase."""
    monkeypatch.setattr(settings, "feedback_enabled", True)
    monkeypatch.setattr(settings, "feedback_db_path", str(tmp_path / "feedback.db"))
    monkeypatch.setattr(feedback_store, "_supabase", lambda: None)
    return tmp_path / "feedback.db"


@pytest.fixture
def client():
    return TestClient(app)


def test_save_and_list_roundtrip(sqlite_feedback):
    ok, backend = save_feedback(
        FeedbackRecord(
            rating="down",
            question="What is CRAG?",
            answer="Something wrong.",
            mode="crag",
            comment="It cited the wrong paper.",
            categories=["wrong_source", "bogus_category"],
            sources=["paper.pdf"],
            session_id="abcdefgh",
        )
    )
    assert ok and backend == "sqlite"
    assert sqlite_feedback.exists()

    rows = list_feedback(limit=10)
    assert len(rows) == 1
    row = rows[0]
    assert row["rating"] == "down"
    assert row["mode"] == "crag"
    assert row["categories"] == ["wrong_source"]  # unknown category dropped
    assert row["sources"] == ["paper.pdf"]


def test_rating_validation(sqlite_feedback):
    with pytest.raises(ValueError):
        save_feedback(FeedbackRecord(rating="meh", question="q", answer="a"))


def test_comment_is_pii_redacted(sqlite_feedback, monkeypatch):
    monkeypatch.setattr(settings, "privacy_output_mode", "redact", raising=False)
    save_feedback(
        FeedbackRecord(
            rating="down",
            question="q",
            answer="a",
            comment="Reach me at alice@example.com about this.",
        )
    )
    row = list_feedback(limit=1)[0]
    assert "alice@example.com" not in row["comment"]


def test_disabled_flag_short_circuits(sqlite_feedback, monkeypatch):
    monkeypatch.setattr(settings, "feedback_enabled", False)
    ok, backend = save_feedback(FeedbackRecord(rating="up", question="q", answer="a"))
    assert not ok and backend == "disabled"
    assert not sqlite_feedback.exists()


def test_summary_aggregates_by_mode_and_category(sqlite_feedback):
    for rating, mode, cats in [
        ("up", "baseline", []),
        ("down", "baseline", ["hallucination"]),
        ("down", "crag", ["hallucination", "incomplete"]),
        ("up", "crag", []),
        ("up", "crag", []),
    ]:
        save_feedback(FeedbackRecord(rating=rating, question="q", answer="a", mode=mode, categories=cats))

    summary = summarize_feedback()
    assert summary["total"] == 5
    assert summary["up"] == 3 and summary["down"] == 2
    by_mode = {r["mode"]: r for r in summary["by_mode"]}
    assert by_mode["baseline"]["negative_rate"] == 0.5
    assert by_mode["crag"]["down"] == 1
    assert summary["top_categories"][0] == {"category": "hallucination", "count": 2}
    assert len(summary["recent_negative"]) == 2


def test_export_builds_regression_candidates(sqlite_feedback, tmp_path):
    save_feedback(FeedbackRecord(rating="up", question="fine", answer="ok", mode="agentic"))
    save_feedback(
        FeedbackRecord(
            rating="down",
            question="Who wrote Self-RAG?",
            answer="Nobody.",
            mode="router",
            comment="Asai et al.",
            categories=["hallucination"],
            sources=["selfrag.pdf"],
        )
    )
    items = build_regression_items()
    assert len(items) == 1
    item = items[0]
    assert item["question"] == "Who wrote Self-RAG?"
    assert item["rejected_answer"] == "Nobody."
    assert item["user_comment"] == "Asai et al."
    assert item["cited_sources"] == ["selfrag.pdf"]
    assert item["expected_keywords"] == []  # human fills this in
    # Serializable for the golden set
    json.dumps(items)


def test_feedback_endpoint_persists(client, sqlite_feedback, monkeypatch):
    monkeypatch.setattr(settings, "require_api_key", False)
    resp = client.post(
        "/feedback",
        json={
            "rating": "down",
            "question": "What is RAG?",
            "answer": "A kind of rug.",
            "mode": "baseline",
            "comment": "Wrong domain entirely.",
            "categories": ["off_topic"],
            "session_id": "sess12345",
            "message_id": "msg-1",
            "sources": ["intro.pdf"],
            "citations": [
                {"index": 1, "chunk_id": "c1", "source": "intro.pdf", "snippet": "RAG is..."}
            ],
            "latency_ms": 1234.5,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["ok"] is True and body["backend"] == "sqlite"

    rows = client.get("/feedback?rating=down").json()
    assert len(rows) == 1
    assert rows[0]["id"] == body["id"]
    assert rows[0]["citations"][0]["chunk_id"] == "c1"

    summary = client.get("/feedback/summary").json()
    assert summary["down"] == 1
    assert summary["top_categories"] == [{"category": "off_topic", "count": 1}]


def test_feedback_endpoint_rejects_bad_rating(client, sqlite_feedback, monkeypatch):
    monkeypatch.setattr(settings, "require_api_key", False)
    resp = client.post(
        "/feedback",
        json={"rating": "sideways", "question": "q", "answer": "a"},
    )
    assert resp.status_code == 422


def test_feedback_endpoint_requires_api_key(client, sqlite_feedback, monkeypatch):
    monkeypatch.setattr(settings, "require_api_key", True)
    monkeypatch.setattr(settings, "api_key", "secret-key-for-tests-1234")
    resp = client.post("/feedback", json={"rating": "up", "question": "q", "answer": "a"})
    assert resp.status_code in (401, 403)


def test_feedback_endpoint_404_when_disabled(client, sqlite_feedback, monkeypatch):
    monkeypatch.setattr(settings, "require_api_key", False)
    monkeypatch.setattr(settings, "feedback_enabled", False)
    resp = client.post("/feedback", json={"rating": "up", "question": "q", "answer": "a"})
    assert resp.status_code == 404


def test_feedback_metric_exported(client, sqlite_feedback, monkeypatch):
    monkeypatch.setattr(settings, "require_api_key", False)
    client.post(
        "/feedback",
        json={"rating": "up", "question": "q", "answer": "a", "mode": "consensus"},
    )
    text = client.get("/metrics").text
    assert 'rag_feedback_total{mode="consensus",rating="up"}' in text
