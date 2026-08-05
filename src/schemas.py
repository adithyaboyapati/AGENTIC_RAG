"""Shared response schemas for CLI and RAG modes."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentResponse:
    answer: str
    mode: str
    sources: list[str] = field(default_factory=list)
    route: str | None = None
    route_reason: str | None = None
    grade_summary: str | None = None
    sub_queries: list[str] | None = None
    decomposition_reason: str | None = None
    steps: list[str] = field(default_factory=list)
