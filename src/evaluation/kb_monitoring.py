"""Knowledge base quality monitoring (Phase 8)."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT, settings


@dataclass
class KBQualityReport:
    active_documents: int = 0
    superseded_documents: int = 0
    quarantined_documents: int = 0
    deleted_documents: int = 0
    total_chunks: int = 0
    avg_chunk_count: float = 0.0
    stale_documents: int = 0
    source_distribution: dict[str, int] = field(default_factory=dict)
    failed_ingest_jobs: int = 0
    warnings: list[str] = field(default_factory=list)


def _registry_db() -> Path:
    return Path(getattr(settings, "document_registry_db_path", PROJECT_ROOT / "data" / "eval" / "document_registry.db"))


def build_kb_quality_report(*, stale_days: int = 90) -> KBQualityReport:
    report = KBQualityReport()
    db = _registry_db()
    if db.exists():
        with sqlite3.connect(str(db)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("select status, source, chunk_count, ingested_at from document_versions").fetchall()
            now = time.time()
            stale_cutoff = now - stale_days * 86400
            sources: dict[str, int] = {}
            chunk_counts: list[int] = []
            for row in rows:
                status = str(row["status"] or "active")
                if status == "active":
                    report.active_documents += 1
                elif status == "superseded":
                    report.superseded_documents += 1
                elif status == "quarantined":
                    report.quarantined_documents += 1
                elif status == "deleted":
                    report.deleted_documents += 1
                source = str(row["source"] or "unknown")
                sources[source] = sources.get(source, 0) + 1
                cc = int(row["chunk_count"] or 0)
                chunk_counts.append(cc)
                report.total_chunks += cc
                if status == "active" and float(row["ingested_at"] or 0) < stale_cutoff:
                    report.stale_documents += 1
            report.source_distribution = sources
            if chunk_counts:
                report.avg_chunk_count = round(sum(chunk_counts) / len(chunk_counts), 2)

    # Ingest job failures from queue if available
    try:
        from src.ingestion.queue import get_job_queue

        jobs = get_job_queue().list_jobs(limit=200)
        report.failed_ingest_jobs = sum(1 for j in jobs if getattr(j, "status", "") == "failed")
    except Exception:
        pass

    if report.stale_documents > 0:
        report.warnings.append("stale_documents_present")
    if report.quarantined_documents > 0:
        report.warnings.append("quarantined_documents_present")

    return report


def list_frequently_irrelevant_sources(limit: int = 10) -> list[dict[str, Any]]:
    """Placeholder hook — requires chunk-level grading telemetry in production."""
    return []
