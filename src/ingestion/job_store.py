"""Redis-backed persistence for ingestion jobs."""

from __future__ import annotations

import json
import logging
from typing import Any

from src.cache.redis_cache import get_redis_client
from src.config import settings
from src.ingestion.queue import IngestionJob, IngestionJobStatus

logger = logging.getLogger(__name__)

_PREFIX = "rag:ingest:job:v1"
_INDEX_KEY = f"{_PREFIX}:index"


def _job_key(job_id: str) -> str:
    return f"{_PREFIX}:{job_id}"


class IngestionJobStore:
    """Optional Redis persistence for ingestion jobs."""

    def available(self) -> bool:
        return get_redis_client() is not None

    def save(self, job: IngestionJob) -> bool:
        client = get_redis_client()
        if client is None:
            return False
        try:
            payload = json.dumps(job.to_dict(), ensure_ascii=False)
            ttl = max(60, int(settings.ingest_job_retention_seconds))
            pipe = client.pipeline()
            pipe.set(_job_key(job.job_id), payload, ex=ttl)
            pipe.zadd(_INDEX_KEY, {job.job_id: job.created_at})
            pipe.expire(_INDEX_KEY, ttl)
            pipe.execute()
            return True
        except Exception:
            logger.debug("Failed to persist ingestion job %s", job.job_id, exc_info=True)
            return False

    def get(self, job_id: str) -> IngestionJob | None:
        client = get_redis_client()
        if client is None:
            return None
        try:
            raw = client.get(_job_key(job_id))
            if not raw:
                return None
            return _deserialize_job(json.loads(raw))
        except Exception:
            logger.debug("Failed to load ingestion job %s", job_id, exc_info=True)
            return None

    def list_recent(self, limit: int = 50) -> list[IngestionJob]:
        client = get_redis_client()
        if client is None:
            return []
        try:
            ids = client.zrevrange(_INDEX_KEY, 0, max(0, limit - 1))
            jobs: list[IngestionJob] = []
            for job_id in ids:
                job = self.get(str(job_id))
                if job is not None:
                    jobs.append(job)
            return jobs
        except Exception:
            logger.debug("Failed to list ingestion jobs", exc_info=True)
            return []


def _deserialize_job(data: dict[str, Any]) -> IngestionJob:
    status_raw = data.get("status", IngestionJobStatus.QUEUED.value)
    try:
        status = IngestionJobStatus(status_raw)
    except ValueError:
        status = IngestionJobStatus.QUEUED
    return IngestionJob(
        job_id=str(data["job_id"]),
        status=status,
        source_paths=list(data.get("source_paths") or []),
        tenant_id=str(data.get("tenant_id") or "default"),
        access_groups=list(data.get("access_groups") or ["public"]),
        progress_pct=float(data.get("progress_pct") or 0.0),
        total_files=int(data.get("total_files") or 0),
        processed_files=int(data.get("processed_files") or 0),
        total_chunks=int(data.get("total_chunks") or 0),
        error=data.get("error"),
        webhook_url=data.get("webhook_url"),
        created_at=float(data.get("created_at") or 0.0),
        completed_at=data.get("completed_at"),
    )


_global_store = IngestionJobStore()


def get_job_store() -> IngestionJobStore:
    return _global_store
