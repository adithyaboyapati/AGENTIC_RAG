"""Explicit conversion boundaries between legacy and canonical contracts."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from langchain_core.documents import Document

from src.contracts.models import Citation, Evidence, RetrievalResult, ScoreBundle


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _chunk_id(doc: Document, index: int) -> str:
    for key in ("chunk_id", "id"):
        value = doc.metadata.get(key)
        if value:
            return str(value)
    return f"chunk-{index}"


def _extract_scores(meta: dict[str, Any]) -> ScoreBundle:
    """Map legacy Document metadata to separate canonical score fields.

    Existing retrieval never writes ``dense_score`` / ``sparse_score`` /
    ``fusion_score`` keys; those are preserved when present. Legacy keys are
    mapped without overwriting explicit canonical values:

    - ``dense_score``  ← metadata ``dense_score``, else ``score`` when no rerank
    - ``sparse_score`` ← metadata ``sparse_score``
    - ``fusion_score`` ← metadata ``fusion_score`` or ``retrieval_score`` (pre-rerank)
    - ``rerank_score`` ← metadata ``rerank_score``
    - ``grade_score``  ← metadata ``grade_score``
    """
    dense = _optional_float(meta.get("dense_score"))
    sparse = _optional_float(meta.get("sparse_score"))
    fusion = _optional_float(meta.get("fusion_score"))
    rerank = _optional_float(meta.get("rerank_score"))
    grade = _optional_float(meta.get("grade_score"))
    legacy_score = _optional_float(meta.get("score"))
    retrieval_score = _optional_float(meta.get("retrieval_score"))

    if fusion is None and retrieval_score is not None:
        fusion = retrieval_score

    if dense is None and legacy_score is not None and rerank is None:
        if sparse is not None or fusion is not None:
            if fusion is None:
                fusion = legacy_score
        else:
            dense = legacy_score

    if fusion is None and legacy_score is not None and rerank is not None:
        fusion = legacy_score if retrieval_score is None else fusion

    return ScoreBundle(
        dense_score=dense,
        sparse_score=sparse,
        fusion_score=fusion,
        rerank_score=rerank,
        grade_score=grade,
    )


def _display_score(scores: ScoreBundle, meta: dict[str, Any]) -> float | None:
    for candidate in (
        scores.rerank_score,
        scores.fusion_score,
        scores.dense_score,
        scores.sparse_score,
        _optional_float(meta.get("score")),
    ):
        if candidate is not None:
            return candidate
    return None


def document_to_retrieval_result(
    doc: Document,
    *,
    query_id: str,
    result_id: str | None = None,
    index: int = 1,
    parent_result_id: str | None = None,
) -> RetrievalResult:
    """Convert a LangChain Document to a canonical RetrievalResult."""
    meta = dict(doc.metadata or {})
    scores = _extract_scores(meta)
    chunk_id = _chunk_id(doc, index)
    section = meta.get("section_title") or meta.get("section_path")

    return RetrievalResult(
        result_id=result_id or _new_id("res"),
        query_id=query_id,
        chunk_id=chunk_id,
        content=doc.page_content or "",
        source=str(meta.get("source", "unknown")),
        page=_optional_int(meta.get("page")),
        section=str(section) if section else None,
        tenant_id=str(meta.get("tenant_id") or "default"),
        scores=scores,
        metadata={
            key: value
            for key, value in meta.items()
            if key
            not in {
                "chunk_id",
                "id",
                "source",
                "page",
                "section_title",
                "section_path",
                "tenant_id",
                "score",
                "dense_score",
                "sparse_score",
                "fusion_score",
                "rerank_score",
                "grade_score",
                "retrieval_score",
            }
        },
        parent_result_id=parent_result_id,
        matched_child_id=str(meta["matched_child_id"])
        if meta.get("matched_child_id") is not None
        else None,
    )


def retrieval_result_to_evidence(
    result: RetrievalResult,
    *,
    evidence_id: str | None = None,
    index: int = 1,
    shown_to_generation: bool = True,
    content: str | None = None,
) -> Evidence:
    """Convert a RetrievalResult to Evidence preserving provenance."""
    return Evidence(
        evidence_id=evidence_id or _new_id("evd"),
        result=result,
        content=content if content is not None else result.content,
        shown_to_generation=shown_to_generation,
        index=index,
    )


def evidence_to_citation(
    evidence: Evidence,
    *,
    snippet_limit: int = 300,
) -> Citation:
    """Convert Evidence to Citation preserving evidence linkage."""
    result = evidence.result
    snippet = evidence.content[:snippet_limit]
    return Citation(
        evidence_id=evidence.evidence_id,
        index=evidence.index,
        chunk_id=result.chunk_id,
        source=result.source,
        page=result.page,
        section=result.section,
        snippet=snippet,
        display_score=_display_score(result.scores, result.metadata),
    )


def documents_to_retrieval_results(
    docs: list[Document],
    *,
    query_id: str,
) -> list[RetrievalResult]:
    """Batch convert Documents to RetrievalResults for one query."""
    return [
        document_to_retrieval_result(doc, query_id=query_id, index=i)
        for i, doc in enumerate(docs, 1)
    ]


def expand_parent_provenance(
    child: RetrievalResult,
    parent: RetrievalResult,
) -> RetrievalResult:
    """Build a parent RetrievalResult that preserves child provenance."""
    meta = dict(parent.metadata)
    meta["expanded_from_child"] = True
    meta["matched_child_id"] = child.chunk_id
    return parent.model_copy(
        update={
            "parent_result_id": child.result_id,
            "matched_child_id": child.chunk_id,
            "scores": child.scores,
            "metadata": meta,
        }
    )
