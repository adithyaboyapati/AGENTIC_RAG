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
class RBACContext:
    """Security and access context for multi-tenancy and RBAC."""

    tenant_id: str = "default"
    user_roles: list[str] = field(default_factory=lambda: ["public"])
    classification: str = "public"

    def roles_key(self) -> str:
        """Normalized representation of roles for cache key generation."""
        return ",".join(sorted({r.strip().lower() for r in self.user_roles if r.strip()})) or "public"

    def is_authorized(
        self,
        doc_tenant_id: str | None = None,
        doc_access_groups: list[str] | str | None = None,
        doc_classification: str | None = None,
    ) -> bool:
        """Check if this context is authorized to access a document chunk."""
        # 1. Tenant check: must match tenant_id or be 'global' / 'public'
        d_tenant = (doc_tenant_id or "default").strip().lower()
        my_tenant = (self.tenant_id or "default").strip().lower()
        if d_tenant not in (my_tenant, "global", "public", "*"):
            return False

        # 2. Access groups / roles check
        if doc_access_groups:
            if isinstance(doc_access_groups, str):
                groups = [g.strip().lower() for g in doc_access_groups.split(",") if g.strip()]
            else:
                groups = [str(g).strip().lower() for g in doc_access_groups]

            my_roles = {r.strip().lower() for r in self.user_roles}
            if "admin" in my_roles or "*" in groups or "public" in groups:
                return True
            if not any(g in my_roles for g in groups):
                return False

        return True


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
    tenant_id: str | None = None
    consensus_score: float | None = None
    critique_summary: str | None = None
    # Set when a node-level output gate hard-stops the graph (poison / critical failure)
    error_code: str | None = None
