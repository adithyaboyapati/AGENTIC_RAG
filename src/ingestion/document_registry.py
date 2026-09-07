"""Document versioning registry for corpus lifecycle (Phase 8)."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT, settings

DOCUMENT_STATUSES = frozenset({"active", "superseded", "deleted", "quarantined"})

_lock = threading.Lock()


@dataclass(frozen=True)
class DocumentVersion:
    document_id: str
    version_id: str
    source: str
    content_hash: str
    ingested_at: float
    effective_at: float
    superseded_at: float | None
    document_status: str
    chunk_count: int
    tenant_id: str = "default"
    filename: str = ""


def _db_path() -> Path:
    path = Path(getattr(settings, "document_registry_db_path", PROJECT_ROOT / "data" / "eval" / "document_registry.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=5.0)
    conn.execute(
        """
        create table if not exists document_versions (
            version_id text primary key,
            document_id text not null,
            source text not null,
            filename text default '',
            content_hash text not null,
            ingested_at real not null,
            effective_at real not null,
            superseded_at real,
            status text not null,
            chunk_count integer default 0,
            tenant_id text default 'default'
        )
        """
    )
    conn.execute("create index if not exists idx_doc_versions_source on document_versions (source)")
    conn.execute("create index if not exists idx_doc_versions_status on document_versions (status)")
    return conn


def content_hash_for_paths(paths: list[str]) -> str:
    h = hashlib.sha256()
    for path in sorted(paths):
        h.update(path.encode("utf-8"))
    return h.hexdigest()[:16]


def register_document_ingest(
    *,
    source: str,
    filename: str,
    chunk_count: int,
    tenant_id: str = "default",
    content_hash: str | None = None,
) -> DocumentVersion:
    """Register a new document version; supersede prior active versions for same source."""
    document_id = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    version_id = uuid.uuid4().hex
    now = time.time()
    digest = content_hash or hashlib.sha256(f"{source}:{chunk_count}:{now}".encode()).hexdigest()[:16]

    with _lock, _conn() as conn:
        conn.execute(
            "update document_versions set status = 'superseded', superseded_at = ? "
            "where source = ? and status = 'active'",
            (now, source),
        )
        conn.execute(
            """
            insert into document_versions (
                version_id, document_id, source, filename, content_hash,
                ingested_at, effective_at, superseded_at, status, chunk_count, tenant_id
            ) values (?, ?, ?, ?, ?, ?, ?, null, 'active', ?, ?)
            """,
            (version_id, document_id, source, filename, digest, now, now, chunk_count, tenant_id),
        )

    return DocumentVersion(
        document_id=document_id,
        version_id=version_id,
        source=source,
        content_hash=digest,
        ingested_at=now,
        effective_at=now,
        superseded_at=None,
        document_status="active",
        chunk_count=chunk_count,
        tenant_id=tenant_id,
        filename=filename,
    )


def list_active_documents(*, tenant_id: str | None = None) -> list[dict[str, Any]]:
    clause = "where status = 'active'"
    params: list[Any] = []
    if tenant_id:
        clause += " and tenant_id = ?"
        params.append(tenant_id)
    with _lock, _conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"select * from document_versions {clause} order by ingested_at desc",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def document_freshness(source: str) -> dict[str, Any]:
    with _lock, _conn() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "select * from document_versions where source = ? and status = 'active' order by ingested_at desc limit 1",
            (source,),
        ).fetchone()
    if not row:
        return {"source": source, "status": "unknown", "freshness": "unknown"}
    age_days = (time.time() - float(row["ingested_at"])) / 86400
    freshness = "fresh" if age_days <= 30 else "aging" if age_days <= 90 else "stale"
    return {
        "source": source,
        "document_id": row["document_id"],
        "version_id": row["version_id"],
        "ingested_at": row["ingested_at"],
        "age_days": round(age_days, 1),
        "freshness": freshness,
        "status": row["status"],
        "chunk_count": row["chunk_count"],
    }
