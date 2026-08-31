"""Federate PDF retrieval with database, sample API, and MCP hits."""

from __future__ import annotations

import logging
from collections.abc import Callable

from langchain_core.documents import Document

from src.config import settings
from src.sources.database import catalog_counts, search_database
from src.sources.mcp_server import mcp_status, search_mcp
from src.sources.sample_api import catalog_status, search_api

logger = logging.getLogger(__name__)

SOURCE_DATABASE = "database"
SOURCE_API = "api"
SOURCE_MCP = "mcp"
SOURCE_PDF = "pdf"

EXTRA_SOURCES = (SOURCE_DATABASE, SOURCE_API, SOURCE_MCP)

RETRIEVAL_TOOL_NAMES = frozenset(
    {"retrieve_docs", "query_database", "query_api", "query_mcp"}
)

TOOL_EMPTY_DETAIL = {
    "retrieve_docs": "No documents found.",
    "query_database": "No database records found.",
    "query_api": "No catalog API results found.",
    "query_mcp": "No MCP lab knowledge found.",
}

_SEARCHERS: dict[str, Callable[[str, int], list[Document]]] = {
    SOURCE_DATABASE: search_database,
    SOURCE_API: search_api,
    SOURCE_MCP: search_mcp,
}


def parse_extra_sources(raw: str | None = None) -> list[str]:
    """Enabled extra sources, preserving a stable order."""
    blob = (raw if raw is not None else settings.extra_sources) or ""
    requested = {part.strip().lower() for part in blob.split(",") if part.strip()}
    return [name for name in EXTRA_SOURCES if name in requested]


def enabled_extra_sources() -> list[str]:
    if not settings.multi_source_enabled:
        return []
    return parse_extra_sources()


def search_source(source: str, query: str, top_k: int = 4) -> list[Document]:
    searcher = _SEARCHERS.get(source)
    if searcher is None:
        return []
    try:
        return searcher(query, top_k)
    except Exception:
        logger.warning("Extra source %s failed", source, exc_info=True)
        return []


def search_extra_sources(
    query: str,
    *,
    sources: list[str] | None = None,
    per_source_k: int = 2,
    max_extra: int | None = None,
) -> list[Document]:
    """Query enabled extra sources and keep the highest-scoring hits."""
    names = sources if sources is not None else enabled_extra_sources()
    cap = max_extra if max_extra is not None else settings.multi_source_max_extra
    collected: list[Document] = []
    for name in names:
        collected.extend(search_source(name, query, top_k=per_source_k))

    collected.sort(
        key=lambda doc: float(doc.metadata.get("score") or 0.0),
        reverse=True,
    )
    seen: set[str] = set()
    unique: list[Document] = []
    for doc in collected:
        key = str(doc.metadata.get("chunk_id") or doc.metadata.get("source") or id(doc))
        if key in seen:
            continue
        seen.add(key)
        unique.append(doc)
        if len(unique) >= cap:
            break
    if unique:
        logger.info(
            "multi-source | query=%r | extra=%d | types=%s",
            query[:120],
            len(unique),
            ",".join(sorted({str(d.metadata.get("source_type")) for d in unique})),
        )
    return unique


def merge_with_pdf(pdf_docs: list[Document], extra_docs: list[Document]) -> list[Document]:
    """Prepend extra-source hits without dropping PDF chunks."""
    if not extra_docs:
        return pdf_docs
    seen = {
        str(doc.metadata.get("chunk_id") or doc.metadata.get("source"))
        for doc in extra_docs
    }
    merged = list(extra_docs)
    for doc in pdf_docs:
        key = str(doc.metadata.get("chunk_id") or doc.metadata.get("source") or id(doc))
        if key in seen:
            continue
        seen.add(key)
        merged.append(doc)
    return merged


def documents_for_tool(tool_name: str, query: str) -> list[Document]:
    """Resolve a retrieval-style tool call to Documents."""
    if tool_name == "retrieve_docs":
        from src.retrieval.retriever import retrieve

        return retrieve(query)
    if tool_name == "query_database":
        return search_database(query)
    if tool_name == "query_api":
        return search_api(query)
    if tool_name == "query_mcp":
        return search_mcp(query)
    return []


def extra_sources_status() -> dict[str, str]:
    """Health payload for /health/ready."""
    if not settings.multi_source_enabled:
        return {"status": "skipped", "detail": "MULTI_SOURCE_ENABLED=false"}
    names = enabled_extra_sources()
    if not names:
        return {"status": "skipped", "detail": "no extra sources configured"}
    parts: list[str] = []
    try:
        if SOURCE_DATABASE in names:
            counts = catalog_counts()
            parts.append(
                f"db papers={counts['papers']} benchmarks={counts['benchmarks']} "
                f"deployments={counts['deployments']}"
            )
        if SOURCE_API in names:
            api = catalog_status()
            parts.append(
                f"api glossary={api['glossary']} systems={api['systems']} "
                f"incidents={api['incidents']}"
            )
        if SOURCE_MCP in names:
            mcp = mcp_status()
            parts.append(
                f"mcp tools={mcp['tools']} experiments={mcp['experiments']}"
            )
    except Exception as exc:
        return {"status": "degraded", "detail": f"source check failed ({type(exc).__name__})"}
    return {"status": "ok", "detail": "; ".join(parts)}


def ensure_sources_ready() -> None:
    """Seed the SQLite catalog so the first query is not a cold create."""
    if not settings.multi_source_enabled:
        return
    if SOURCE_DATABASE not in enabled_extra_sources():
        return
    from src.sources.database import ensure_seeded

    ensure_seeded()
