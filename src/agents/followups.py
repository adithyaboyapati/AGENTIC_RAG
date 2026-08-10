"""Generate grounded follow-up questions after an agent answer."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.llm import get_llm
from src.prompts import FOLLOWUP_PROMPT

logger = logging.getLogger(__name__)

_NON_CORPUS_SOURCES = frozenset({"web search", "tools"})


class FollowUpQuestions(BaseModel):
    """Structured output: three next questions for the user."""

    questions: list[str] = Field(
        min_length=3,
        max_length=3,
        description="Exactly three distinct follow-up questions",
    )


followup_chain = FOLLOWUP_PROMPT | get_llm().with_structured_output(FollowUpQuestions)


def _build_context(question: str, answer: str, sources: list[str]) -> str:
    """Prefer fresh retrieval snippets; fall back to answer + source labels."""
    corpus_sources = [s for s in sources if s.lower() not in _NON_CORPUS_SOURCES]
    if corpus_sources:
        try:
            from src.retrieval.retriever import format_docs, retrieve

            docs = retrieve(question, top_k=3)
            if docs:
                return format_docs(docs)
        except Exception:
            logger.warning("Follow-up context retrieval failed; using answer fallback", exc_info=True)

    parts = [f"Answer:\n{answer[:2000]}"]
    if sources:
        parts.append("Sources: " + ", ".join(sources))
    return "\n\n".join(parts)


def generate_follow_ups(
    question: str,
    answer: str,
    sources: list[str] | None = None,
) -> list[str]:
    """Return up to 3 follow-up questions, or [] on failure / empty answer."""
    if not answer or not answer.strip():
        return []

    sources = sources or []
    context = _build_context(question, answer, sources)

    try:
        result = followup_chain.invoke(
            {
                "question": question,
                "answer": answer[:2500],
                "context": context[:6000],
            }
        )
    except Exception:
        logger.warning("Follow-up generation failed", exc_info=True)
        return []

    cleaned: list[str] = []
    seen: set[str] = set()
    for q in result.questions:
        text = " ".join(q.split()).strip()
        if not text:
            continue
        key = text.lower()
        if key == question.strip().lower() or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) == 3:
            break
    return cleaned
