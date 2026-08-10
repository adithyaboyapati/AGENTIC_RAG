"""Shared response schemas for CLI and RAG modes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Citation:
    """Chunk-level provenance for UI and evaluation."""

    index: int
    chunk_id: str
    source: str
    page: int | None = None
    section: str | None = None
    snippet: str = ""
    score: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def label(self) -> str:
        label = self.source
        if self.page is not None:
            label = f"{label}#p{self.page}"
        if self.section:
            label = f"{label} [{self.section}]"
        return label


@dataclass
class AgentResponse:
    answer: str
    mode: str
    sources: list[str] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    context_docs: list[str] = field(default_factory=list)
    route: str | None = None
    route_reason: str | None = None
    grade_summary: str | None = None
    sub_queries: list[str] | None = None
    decomposition_reason: str | None = None
    steps: list[str] = field(default_factory=list)
    follow_ups: list[str] = field(default_factory=list)
    # Set when a node-level output gate hard-stops the graph (poison / critical failure)
    error_code: str | None = None
