"""Document catalog and browser upload endpoints for the chat UI."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from src.api.rate_limit import enforce_client_rate_limit
from src.api.security import resolve_request_rbac, verify_api_key
from src.config import settings
from src.security.paths import ingest_allowed_roots, resolve_ingest_path

logger = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_FILENAME = 120
_PDF_MAGIC = b"%PDF"


class IndexedDocument(BaseModel):
    source: str
    filename: str
    chunk_count: int
    tenant_id: str = "default"
    page_count: int | None = None


class DocumentListResponse(BaseModel):
    documents: list[IndexedDocument]
    total_chunks: int = 0


class DeleteDocumentResponse(BaseModel):
    source: str
    deleted_chunks: int


class UploadFileResult(BaseModel):
    filename: str
    saved_path: str
    job_id: str
    status: str
    error: str | None = None


class UploadResponse(BaseModel):
    files: list[UploadFileResult] = Field(default_factory=list)
    job_ids: list[str] = Field(default_factory=list)


def _uploads_dir() -> Path:
    roots = ingest_allowed_roots()
    if not roots:
        raise HTTPException(status_code=500, detail="No ingest roots configured")
    dest = roots[0] / "uploads"
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def _safe_filename(name: str) -> str:
    raw = Path(name or "document.pdf").name
    stem = _SAFE_NAME.sub("_", Path(raw).stem).strip("._") or "document"
    return f"{stem[:_MAX_FILENAME]}.pdf"


def _max_bytes() -> int:
    return max(1, int(settings.ingest_max_upload_mb)) * 1024 * 1024


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(_: None = Depends(verify_api_key)) -> DocumentListResponse:
    """List unique sources currently indexed in the vector store."""
    from src.ingestion.ingest import list_indexed_documents

    docs = await asyncio.to_thread(list_indexed_documents)
    total = sum(int(d.get("chunk_count") or 0) for d in docs)
    return DocumentListResponse(
        documents=[IndexedDocument(**d) for d in docs],
        total_chunks=total,
    )


@router.delete("/documents", response_model=DeleteDocumentResponse)
async def delete_document(
    source: str = Query(..., min_length=1, max_length=1024),
    _auth: None = Depends(verify_api_key),
    _rate: None = Depends(enforce_client_rate_limit),
) -> DeleteDocumentResponse:
    """Remove all chunks for an indexed source."""
    from src.ingestion.ingest import remove_indexed_source

    deleted = await asyncio.to_thread(remove_indexed_source, source)
    if deleted <= 0:
        raise HTTPException(status_code=404, detail=f"No chunks found for source '{source}'")
    return DeleteDocumentResponse(source=source, deleted_chunks=deleted)


@router.post("/ingest/upload", response_model=UploadResponse, status_code=202)
async def upload_documents(
    files: list[UploadFile] = File(...),
    _auth: None = Depends(verify_api_key),
    _rate: None = Depends(enforce_client_rate_limit),
) -> UploadResponse:
    """Accept PDF uploads, store them under the ingest allowlist, and enqueue indexing."""
    from src.ingestion.queue import get_ingestion_queue

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    max_files = max(1, int(settings.ingest_max_upload_files))
    if len(files) > max_files:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files (max {max_files} per request)",
        )

    dest_dir = _uploads_dir()
    max_bytes = _max_bytes()
    rbac = resolve_request_rbac(None, ["public"])
    queue = get_ingestion_queue()
    results: list[UploadFileResult] = []
    job_ids: list[str] = []

    for upload in files:
        original = upload.filename or "document.pdf"
        content_type = (upload.content_type or "").lower()
        if not original.lower().endswith(".pdf") and "pdf" not in content_type:
            raise HTTPException(
                status_code=400,
                detail=f"Only PDF files are supported (got {original})",
            )

        data = await upload.read()
        if not data:
            raise HTTPException(status_code=400, detail=f"{original} is empty")
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"{original} exceeds the {settings.ingest_max_upload_mb} MB upload limit"
                ),
            )
        if not data.startswith(_PDF_MAGIC):
            raise HTTPException(
                status_code=400,
                detail=f"{original} is not a valid PDF",
            )

        saved = dest_dir / f"{uuid.uuid4().hex[:12]}_{_safe_filename(original)}"
        await asyncio.to_thread(saved.write_bytes, data)
        resolved = resolve_ingest_path(str(saved))
        job = queue.submit_job(
            source_paths=[str(resolved)],
            tenant_id=rbac.tenant_id,
            access_groups=list(rbac.user_roles),
        )
        job_ids.append(job.job_id)
        results.append(
            UploadFileResult(
                filename=original,
                saved_path=str(resolved),
                job_id=job.job_id,
                status=job.status.value if hasattr(job.status, "value") else str(job.status),
            )
        )
        logger.info("Queued upload %s as job %s", saved.name, job.job_id)

    return UploadResponse(files=results, job_ids=job_ids)
