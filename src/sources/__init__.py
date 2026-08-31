"""Extra knowledge sources: SQLite catalog, sample ops API, and lab MCP."""

from src.sources.federation import (
    RETRIEVAL_TOOL_NAMES,
    documents_for_tool,
    enabled_extra_sources,
    ensure_sources_ready,
    search_extra_sources,
)

__all__ = [
    "RETRIEVAL_TOOL_NAMES",
    "documents_for_tool",
    "enabled_extra_sources",
    "ensure_sources_ready",
    "search_extra_sources",
]
