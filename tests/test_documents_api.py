"""Tests for document catalog, upload, runtime config, and pipeline SSE."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.api.server import app
from src.config import settings
from src.runner import build_pipeline_payload
from src.schemas import AgentResponse, Citation


def test_runtime_config_exposes_models_not_secrets(monkeypatch):
    monkeypatch.setattr(settings, "require_api_key", False)
    client = TestClient(app)
    resp = client.get("/config")
    assert resp.status_code == 200
    body = resp.json()
    assert "openai_model" in body
    assert "api_key" not in body
    assert "openai_api_key" not in body
    assert body["ingest_max_upload_mb"] >= 1


def test_list_documents_aggregates_sources(monkeypatch):
    monkeypatch.setattr(settings, "require_api_key", False)
    client = TestClient(app)
    docs = [
        {
            "source": "/data/sample_docs/rag.pdf",
            "filename": "rag.pdf",
            "chunk_count": 12,
            "tenant_id": "default",
            "page_count": 8,
        }
    ]
    with patch("src.ingestion.ingest.list_indexed_documents", return_value=docs):
        resp = client.get("/documents")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_chunks"] == 12
    assert body["documents"][0]["filename"] == "rag.pdf"


def test_delete_document_404_when_missing(monkeypatch):
    monkeypatch.setattr(settings, "require_api_key", False)
    client = TestClient(app)
    with patch("src.ingestion.ingest.remove_indexed_source", return_value=0):
        resp = client.delete("/documents", params={"source": "missing.pdf"})
    assert resp.status_code == 404


def test_delete_document_success(monkeypatch):
    monkeypatch.setattr(settings, "require_api_key", False)
    client = TestClient(app)
    with patch("src.ingestion.ingest.remove_indexed_source", return_value=7):
        resp = client.delete("/documents", params={"source": "rag.pdf"})
    assert resp.status_code == 200
    assert resp.json()["deleted_chunks"] == 7


def test_upload_rejects_non_pdf(monkeypatch):
    monkeypatch.setattr(settings, "require_api_key", False)
    client = TestClient(app)
    resp = client.post(
        "/ingest/upload",
        files=[("files", ("notes.txt", b"hello", "text/plain"))],
    )
    assert resp.status_code == 400
    assert "PDF" in resp.json()["detail"]


def test_upload_rejects_invalid_pdf_magic(monkeypatch):
    monkeypatch.setattr(settings, "require_api_key", False)
    client = TestClient(app)
    resp = client.post(
        "/ingest/upload",
        files=[("files", ("fake.pdf", b"not-a-pdf", "application/pdf"))],
    )
    assert resp.status_code == 400
    assert "valid PDF" in resp.json()["detail"]


def test_upload_queues_pdf(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "require_api_key", False)
    monkeypatch.setattr(settings, "ingest_allowed_roots", str(tmp_path))
    client = TestClient(app)

    fake_job = MagicMock()
    fake_job.job_id = "job-abc"
    fake_job.status.value = "queued"

    fake_queue = MagicMock()
    fake_queue.submit_job.return_value = fake_job

    with patch("src.ingestion.queue.get_ingestion_queue", return_value=fake_queue):
        resp = client.post(
            "/ingest/upload",
            files=[("files", ("paper.pdf", b"%PDF-1.4 test", "application/pdf"))],
        )

    assert resp.status_code == 202
    body = resp.json()
    assert body["job_ids"] == ["job-abc"]
    assert body["files"][0]["filename"] == "paper.pdf"
    fake_queue.submit_job.assert_called_once()
    saved = tmp_path / "uploads"
    assert saved.exists()
    assert any(p.suffix == ".pdf" for p in saved.iterdir())


def test_pipeline_payload_uses_backend_fields():
    result = AgentResponse(
        answer="Self-RAG grades retrieved documents.",
        mode="crag",
        sources=["rag.pdf#p3"],
        citations=[
            Citation(
                index=1,
                chunk_id="c1",
                source="rag.pdf",
                page=3,
                snippet="Self-RAG",
                score=0.91,
            )
        ],
        context_docs=["Self-RAG grades retrieved documents before generation."],
        route="retrieval",
        route_reason="needs corpus",
        grade_summary="2/3 relevant",
        steps=["Retrieved 3 chunks", "Graded documents"],
        follow_ups=["What is CRAG?"],
    )
    payload = build_pipeline_payload(
        question="What is Self-RAG?",
        mode="crag",
        result=result,
        sanitized_question="What is Self-RAG?",
        effective_question="What is Self-RAG?",
        latency_ms=120.0,
    )
    ids = [s["id"] for s in payload["stages"]]
    assert ids == [
        "query",
        "processing",
        "tools",
        "retrieval",
        "chunks",
        "rerank",
        "context",
        "generation",
        "answer",
    ]
    chunks = next(s for s in payload["stages"] if s["id"] == "chunks")
    assert chunks["data"]["count"] == 1
    assert chunks["data"]["citations"][0]["chunk_id"] == "c1"
    context = next(s for s in payload["stages"] if s["id"] == "context")
    assert context["data"]["doc_count"] == 1
    answer = next(s for s in payload["stages"] if s["id"] == "answer")
    assert "Self-RAG" in answer["data"]["answer"]
