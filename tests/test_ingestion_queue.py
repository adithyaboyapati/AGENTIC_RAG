"""Tests for Asynchronous Ingestion Queue, Job Polling, and Webhooks."""

import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.server import app
from src.config import PROJECT_ROOT
from src.ingestion.queue import (
    IngestionJobStatus,
    IngestionQueue,
    sign_webhook_payload,
)


def test_sign_webhook_payload():
    payload = b'{"event":"test"}'
    secret = "supersecretkey123"
    sig = sign_webhook_payload(payload, secret)
    assert sig.startswith("sha256=")
    assert len(sig) == 64 + 7


def test_ingestion_queue_lifecycle_success(tmp_path):
    queue = IngestionQueue(max_workers=1)

    pdf_file = PROJECT_ROOT / "data" / "sample_docs" / "rag.pdf"
    if not pdf_file.exists():
        # Create a dummy test file
        test_file = tmp_path / "doc.txt"
        test_file.write_text("Hello world")
        target_path = str(test_file)
    else:
        target_path = str(pdf_file)

    # Mock ingest_documents so we don't re-embed during fast unit tests
    with patch("src.ingestion.ingest.ingest_documents", return_value=15):
        job = queue.submit_job(
            source_paths=[target_path],
            tenant_id="tenant_x",
            access_groups=["admin"],
        )

        assert job.job_id.startswith("job-")
        assert job.tenant_id == "tenant_x"
        assert job.total_files == 1

        # Wait for worker thread to process
        for _ in range(50):
            status_job = queue.get_job(job.job_id)
            if status_job and status_job.status in (
                IngestionJobStatus.COMPLETED,
                IngestionJobStatus.FAILED,
            ):
                break
            time.sleep(0.05)

        finished = queue.get_job(job.job_id)
        assert finished is not None
        assert finished.status == IngestionJobStatus.COMPLETED
        assert finished.progress_pct == 100.0
        assert finished.total_chunks == 15
        assert finished.completed_at is not None


def test_ingestion_queue_lifecycle_failure():
    queue = IngestionQueue(max_workers=1)

    job = queue.submit_job(
        source_paths=["/nonexistent/path/never_exists.pdf"],
        tenant_id="default",
    )

    for _ in range(50):
        status_job = queue.get_job(job.job_id)
        if status_job and status_job.status in (
            IngestionJobStatus.COMPLETED,
            IngestionJobStatus.FAILED,
        ):
            break
        time.sleep(0.05)

    finished = queue.get_job(job.job_id)
    assert finished is not None
    assert finished.status == IngestionJobStatus.FAILED
    assert finished.error is not None
    assert "does not exist" in finished.error


def test_ingest_api_endpoints(monkeypatch):
    monkeypatch.setattr("src.api.server.auth_required", lambda: False)
    client = TestClient(app)

    with patch("src.ingestion.ingest.ingest_documents", return_value=5):
        # 1. Submit Job
        pdf_path = str(PROJECT_ROOT / "data" / "sample_docs" / "rag.pdf")
        resp = client.post(
            "/ingest/jobs",
            json={
                "source_paths": [pdf_path],
                "tenant_id": "api_tenant",
                "access_groups": ["engineering"],
            },
        )
        assert resp.status_code == 202
        data = resp.json()
        job_id = data["job_id"]
        assert job_id.startswith("job-")
        assert data["tenant_id"] == "api_tenant"

        # 2. Poll Job
        time.sleep(0.2)
        get_resp = client.get(f"/ingest/jobs/{job_id}")
        assert get_resp.status_code == 200
        job_data = get_resp.json()
        assert job_data["job_id"] == job_id
        assert job_data["status"] in ("queued", "processing", "completed")

        # 3. List Jobs
        list_resp = client.get("/ingest/jobs?limit=10")
        assert list_resp.status_code == 200
        jobs = list_resp.json()
        assert any(j["job_id"] == job_id for j in jobs)

        # 4. Missing Job 404
        missing_resp = client.get("/ingest/jobs/nonexistent-job-id")
        assert missing_resp.status_code == 404
