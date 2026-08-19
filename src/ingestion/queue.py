"""
Asynchronous Ingestion Job Queue, Progress Tracking, and Webhooks.

Allows non-blocking background document ingestion with polling endpoints
and HMAC-signed webhook delivery.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from src.config import settings

logger = logging.getLogger(__name__)


class IngestionJobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class IngestionJob:
    """State of an asynchronous document ingestion job."""

    job_id: str
    status: IngestionJobStatus
    source_paths: list[str]
    tenant_id: str = "default"
    access_groups: list[str] = field(default_factory=lambda: ["public"])
    progress_pct: float = 0.0
    total_files: int = 0
    processed_files: int = 0
    total_chunks: int = 0
    error: str | None = None
    webhook_url: str | None = None
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


def sign_webhook_payload(payload_bytes: bytes, secret: str) -> str:
    """Generate SHA256 HMAC signature for webhook verification."""
    mac = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def _dispatch_webhook(job: IngestionJob) -> None:
    """Send an HTTP POST webhook callback upon job completion."""
    if not job.webhook_url:
        return

    payload = {
        "event": f"ingestion.job.{job.status.value}",
        "timestamp": time.time(),
        "job": job.to_dict(),
    }
    raw_payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Agentic-RAG-Ingestion-Webhook/1.0",
    }
    if settings.webhook_secret:
        headers["X-Hub-Signature-256"] = sign_webhook_payload(
            raw_payload, settings.webhook_secret
        )

    try:
        import urllib.request

        req = urllib.request.Request(
            job.webhook_url,
            data=raw_payload,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            logger.info(
                "Webhook delivered for job %s to %s | HTTP %d",
                job.job_id,
                job.webhook_url,
                resp.status,
            )
    except Exception:
        logger.warning(
            "Webhook delivery failed for job %s to %s",
            job.job_id,
            job.webhook_url,
            exc_info=True,
        )


class IngestionQueue:
    """Thread-safe queue and executor for asynchronous document ingestion jobs."""

    def __init__(self, max_workers: int = 2) -> None:
        self.max_workers = max_workers
        self._lock = threading.Lock()
        self._jobs: dict[str, IngestionJob] = {}
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="ingest-worker",
        )

    def submit_job(
        self,
        source_paths: list[str],
        tenant_id: str = "default",
        access_groups: list[str] | None = None,
        webhook_url: str | None = None,
    ) -> IngestionJob:
        """Create and queue a new ingestion job."""
        job_id = f"job-{uuid.uuid4().hex[:12]}"
        job = IngestionJob(
            job_id=job_id,
            status=IngestionJobStatus.QUEUED,
            source_paths=source_paths,
            tenant_id=tenant_id or "default",
            access_groups=access_groups or ["public"],
            total_files=len(source_paths),
            webhook_url=webhook_url,
        )

        with self._lock:
            # Enforce retention limit
            self._cleanup_old_jobs()
            self._jobs[job_id] = job

        logger.info("Ingestion job queued: %s (%d file(s))", job_id, len(source_paths))
        self._executor.submit(self._run_job, job_id)
        return job

    def get_job(self, job_id: str) -> IngestionJob | None:
        """Retrieve job by ID."""
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self, limit: int = 50) -> list[IngestionJob]:
        """List recent jobs sorted by creation time descending."""
        with self._lock:
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def _cleanup_old_jobs(self) -> None:
        """Remove jobs older than the retention threshold."""
        now = time.time()
        ttl = float(settings.ingest_job_retention_seconds)
        to_delete = [
            jid
            for jid, j in self._jobs.items()
            if j.completed_at and (now - j.completed_at) > ttl
        ]
        for jid in to_delete:
            del self._jobs[jid]

    def _run_job(self, job_id: str) -> None:
        """Worker thread entry point for processing an ingestion job."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = IngestionJobStatus.PROCESSING
            job.progress_pct = 5.0

        start_time = time.time()
        total_chunks = 0

        try:
            from src.ingestion.ingest import ingest_documents

            # Process files
            for idx, path_str in enumerate(job.source_paths, 1):
                p = Path(path_str)
                if not p.exists():
                    raise FileNotFoundError(f"Source path does not exist: {path_str}")

                # Call ingest
                count = ingest_documents(
                    p,
                    tenant_id=job.tenant_id,
                    access_groups=job.access_groups,
                )
                total_chunks += count

                # Update progress
                with self._lock:
                    job.processed_files = idx
                    job.total_chunks = total_chunks
                    job.progress_pct = round(
                        5.0 + (90.0 * (idx / max(1, job.total_files))), 1
                    )

            # Invalidate caches so new docs are immediately retrievable
            try:
                from src.retrieval.retriever import invalidate_bm25_cache

                invalidate_bm25_cache()
            except Exception:
                pass

            duration = time.time() - start_time
            with self._lock:
                job.status = IngestionJobStatus.COMPLETED
                job.progress_pct = 100.0
                job.completed_at = time.time()

            try:
                from src.api.metrics import (
                    record_ingest_chunks,
                    record_ingest_duration,
                    record_ingest_job,
                )

                record_ingest_job("completed")
                record_ingest_chunks(total_chunks)
                record_ingest_duration(duration)
            except Exception:
                pass

            logger.info(
                "Ingestion job %s completed in %.2fs | chunks=%d",
                job_id,
                duration,
                total_chunks,
            )

        except Exception as exc:
            duration = time.time() - start_time
            logger.exception("Ingestion job %s failed: %s", job_id, exc)
            with self._lock:
                job.status = IngestionJobStatus.FAILED
                job.error = str(exc)
                job.completed_at = time.time()

            try:
                from src.api.metrics import record_ingest_duration, record_ingest_job

                record_ingest_job("failed")
                record_ingest_duration(duration)
            except Exception:
                pass

        finally:
            _dispatch_webhook(job)


# Singleton queue instance
_global_queue = IngestionQueue(max_workers=settings.ingest_max_concurrent_jobs)


def get_ingestion_queue() -> IngestionQueue:
    return _global_queue
