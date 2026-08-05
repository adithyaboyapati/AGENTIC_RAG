"""
Phase 3: Document Grader — Corrective RAG (CRAG).

Uses LangChain structured output to grade each retrieved chunk.
Only relevant chunks are passed to the generator.
"""

from __future__ import annotations

from langchain_core.documents import Document
from pydantic import BaseModel, Field

from src.config import settings
from src.llm import get_llm
from src.prompts import GRADER_PROMPT
from src.retrieval.retriever import format_docs


class DocumentGrade(BaseModel):
    """Relevance grade for a single chunk (1-based index)."""

    chunk_index: int = Field(description="1-based index matching the chunk label")
    relevant: bool = Field(description="Whether the chunk helps answer the question")
    score: float = Field(ge=0.0, le=1.0, description="Relevance score from 0 to 1")
    reason: str = Field(description="Brief reason for the grade")


class GradingResult(BaseModel):
    """Structured grading output for all retrieved chunks."""

    grades: list[DocumentGrade]


grader_chain = GRADER_PROMPT | get_llm().with_structured_output(GradingResult)


def grade_documents(question: str, documents: list[Document]) -> tuple[list[Document], GradingResult]:
    """
    Grade retrieved documents and return only those above the relevance threshold.

    Returns:
        (filtered_documents, full_grading_result)
    """
    if not documents:
        return [], GradingResult(grades=[])

    formatted = format_docs(documents)
    result: GradingResult = grader_chain.invoke({"question": question, "documents": formatted})

    grade_map = {g.chunk_index: g for g in result.grades}
    threshold = settings.grader_relevance_threshold

    filtered: list[Document] = []
    for i, doc in enumerate(documents, 1):
        grade = grade_map.get(i)
        if grade and grade.relevant and grade.score >= threshold:
            filtered.append(doc)

    return filtered, result


def summarize_grades(result: GradingResult) -> str:
    """Human-readable summary for agent step logs."""
    if not result.grades:
        return "No documents to grade"

    relevant = sum(1 for g in result.grades if g.relevant and g.score >= settings.grader_relevance_threshold)
    total = len(result.grades)
    avg = sum(g.score for g in result.grades) / total
    return f"{relevant}/{total} chunks relevant (avg score: {avg:.2f})"
