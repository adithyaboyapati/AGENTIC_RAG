"""Convert canonical contract responses into API-facing schema objects."""

from __future__ import annotations

from src.contracts.models import AgentResponse as CanonicalAgentResponse
from src.schemas import AgentResponse as ApiAgentResponse
from src.schemas import Citation as ApiCitation


def canonical_to_api_response(
    canonical: CanonicalAgentResponse,
    *,
    display_mode: str = "canonical",
    route_reason: str | None = None,
) -> ApiAgentResponse:
    """Map canonical AgentResponse to the API/CLI AgentResponse schema."""
    citations: list[ApiCitation] = []
    sources: list[str] = []
    seen_sources: set[str] = set()

    for index, citation in enumerate(canonical.citations or (), 1):
        api_citation = ApiCitation(
            index=index,
            chunk_id=citation.chunk_id,
            source=citation.source,
            page=citation.page,
            section=citation.section,
            snippet=(citation.snippet or "")[:300],
            score=citation.display_score,
        )
        citations.append(api_citation)
        label = api_citation.label()
        if label not in seen_sources:
            seen_sources.add(label)
            sources.append(label)

    steps = [event.message for event in (canonical.trace or ()) if event.message]

    verification_summary: str | None = None
    verification_status: str | None = None
    confidence: float | None = None
    response_status: str | None = None
    if canonical.verification is not None:
        verification_summary = (
            f"{canonical.verification.outcome}"
            f" (faithfulness={canonical.verification.faithfulness:.2f})"
            if canonical.verification.faithfulness is not None
            else canonical.verification.outcome
        )
        verification_status = canonical.verification.outcome
        confidence = canonical.verification.confidence

    response_status = canonical.response_status or ("error" if canonical.error_code else "answered")

    return ApiAgentResponse(
        answer=canonical.answer,
        mode=display_mode,
        sources=sources,
        citations=citations,
        context_docs=[],
        route=canonical.route,
        route_reason=route_reason or canonical.strategy,
        grade_summary=verification_summary,
        steps=steps,
        follow_ups=list(canonical.follow_ups or []),
        tenant_id=canonical.tenant_id,
        error_code=canonical.error_code,
        verification_status=verification_status,
        confidence=confidence,
        response_status=response_status,
        pipeline_version=f"canonical-v1",
    )


def safe_abstention_response(
    *,
    mode: str,
    reason: str,
    tenant_id: str | None = None,
) -> ApiAgentResponse:
    """Production-safe response when canonical execution or verification fails."""
    return ApiAgentResponse(
        answer=(
            "I couldn't produce a verified answer for this request. "
            "Please try again or rephrase your question."
        ),
        mode=mode,
        steps=[f"safe_abstention:{reason}"],
        tenant_id=tenant_id,
        error_code=reason,
    )
