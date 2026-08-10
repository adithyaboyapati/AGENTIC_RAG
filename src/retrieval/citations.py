"""Build citation / context payloads from LangChain Documents."""

from __future__ import annotations

from langchain_core.documents import Document

from src.schemas import AgentResponse, Citation


def _page(doc: Document) -> int | None:
    raw = doc.metadata.get("page")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _score(doc: Document) -> float | None:
    raw = doc.metadata.get("score")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _chunk_id(doc: Document, index: int) -> str:
    for key in ("chunk_id", "id"):
        value = doc.metadata.get(key)
        if value:
            return str(value)
    return f"chunk-{index}"


def docs_to_citations(docs: list[Document]) -> list[Citation]:
    citations: list[Citation] = []
    for i, doc in enumerate(docs, 1):
        section = doc.metadata.get("section_title") or doc.metadata.get("section_path")
        citations.append(
            Citation(
                index=i,
                chunk_id=_chunk_id(doc, i),
                source=str(doc.metadata.get("source", "unknown")),
                page=_page(doc),
                section=str(section) if section else None,
                snippet=(doc.page_content or "")[:300],
                score=_score(doc),
            )
        )
    return citations


def docs_to_sources(docs: list[Document]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for doc in docs:
        source = str(doc.metadata.get("source", "unknown"))
        page = doc.metadata.get("page")
        section = doc.metadata.get("section_title") or doc.metadata.get("section_path")
        label = source
        if page is not None:
            label = f"{label}#p{page}"
        if section:
            label = f"{label} [{section}]"
        if label not in seen:
            seen.add(label)
            labels.append(label)
    return labels


def docs_to_context(docs: list[Document]) -> list[str]:
    return [doc.page_content for doc in docs if doc.page_content]


def build_response(
    *,
    answer: str,
    mode: str,
    docs: list[Document] | None = None,
    sources: list[str] | None = None,
    context_docs: list[str] | None = None,
    citations: list[Citation] | None = None,
    **kwargs,
) -> AgentResponse:
    """Assemble AgentResponse with consistent citation / context fields."""
    docs = docs or []
    resolved_citations = citations if citations is not None else docs_to_citations(docs)
    resolved_context = context_docs if context_docs is not None else docs_to_context(docs)
    if sources is not None:
        resolved_sources = sources
    elif resolved_citations:
        resolved_sources = []
        seen: set[str] = set()
        for citation in resolved_citations:
            label = citation.label()
            if label not in seen:
                seen.add(label)
                resolved_sources.append(label)
    else:
        resolved_sources = docs_to_sources(docs)

    return AgentResponse(
        answer=answer,
        mode=mode,
        sources=resolved_sources,
        citations=resolved_citations,
        context_docs=resolved_context,
        **kwargs,
    )
