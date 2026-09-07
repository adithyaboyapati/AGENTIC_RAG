"""Canonical evidence management boundary."""

from __future__ import annotations

from langchain_core.documents import Document

from src.agents.grader import grade_documents
from src.config import settings
from src.contracts.conversions import document_to_retrieval_result, retrieval_result_to_evidence
from src.contracts.models import Evidence, RetrievalResult
from src.ingestion.parent_store import expand_children_to_parents


def _result_key(result: RetrievalResult) -> str:
    return result.chunk_id or result.result_id


def deduplicate_evidence(items: list[Evidence]) -> list[Evidence]:
    seen: set[str] = set()
    unique: list[Evidence] = []
    for item in items:
        key = _result_key(item.result)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def grade_evidence(question: str, items: list[Evidence]) -> list[Evidence]:
    """Grade evidence relevance using existing grader; attach grade_score."""
    if not items:
        return []
    docs = [
        Document(page_content=item.content, metadata={"chunk_id": item.result.chunk_id})
        for item in items
    ]
    filtered_docs, grading = grade_documents(question, docs)
    allowed_ids = {
        (doc.metadata or {}).get("chunk_id")
        for doc in filtered_docs
    }
    grade_map = {
        (docs[g.chunk_index - 1].metadata or {}).get("chunk_id"): g
        for g in grading.grades
        if 1 <= g.chunk_index <= len(docs)
    }

    kept: list[Evidence] = []
    for item in items:
        chunk_id = item.result.chunk_id
        if chunk_id not in allowed_ids:
            continue
        grade = grade_map.get(chunk_id)
        if grade is None:
            kept.append(item)
            continue
        scores = item.result.scores.model_copy(update={"grade_score": grade.score})
        updated_result = item.result.model_copy(update={"scores": scores})
        kept.append(item.model_copy(update={"result": updated_result}))
    return kept


def expand_parent_evidence(items: list[Evidence]) -> list[Evidence]:
    """Expand child evidence to parent sections while preserving provenance."""
    if not items or not settings.expand_to_parent:
        return items
    docs = [
        Document(
            page_content=item.content,
            metadata={
                **item.result.metadata,
                "chunk_id": item.result.chunk_id,
                "score": item.result.scores.fusion_score or item.result.scores.dense_score,
                "rerank_score": item.result.scores.rerank_score,
                "retrieval_score": item.result.scores.fusion_score,
            },
        )
        for item in items
    ]
    expanded_docs = expand_children_to_parents(docs)
    expanded: list[Evidence] = []
    for i, doc in enumerate(expanded_docs, 1):
        child = items[min(i - 1, len(items) - 1)]
        result = document_to_retrieval_result(
            doc,
            query_id=child.result.query_id,
            parent_result_id=child.result.result_id,
        )
        result = result.model_copy(update={"scores": child.result.scores})
        expanded.append(
            retrieval_result_to_evidence(
                result,
                index=i,
                shown_to_generation=False,
                content=doc.page_content,
            )
        )
    return expanded


def mark_irrelevant(items: list[Evidence], *, reason: str = "irrelevant") -> list[Evidence]:
    return [
        item.model_copy(
            update={
                "shown_to_generation": False,
                "included_in_context": False,
                "excluded_reason": reason,
            }
        )
        for item in items
    ]


def process_evidence_candidates(
    question: str,
    candidates: list[Evidence],
) -> list[Evidence]:
    """Full evidence pipeline: dedupe → grade → parent expand → dedupe."""
    pipeline = deduplicate_evidence(candidates)
    pipeline = grade_evidence(question, pipeline)
    pipeline = expand_parent_evidence(pipeline)
    return deduplicate_evidence(pipeline)
