"""Retrieval adapter: legacy Documents → canonical RetrievalResult / Evidence."""

from __future__ import annotations

from langchain_core.documents import Document

from src.contracts.conversions import (
    document_to_retrieval_result,
    retrieval_result_to_evidence,
)
from src.contracts.models import Evidence, PlannedQuery, RetrievalPlan, RetrievalResult
from src.retrieval.retriever import retrieve
from src.schemas import RBACContext


def retrieve_candidates(
    query: str,
    *,
    query_id: str,
    rbac_context: RBACContext,
    top_k: int | None = None,
) -> list[RetrievalResult]:
    """Retrieve via existing pipeline and convert without mutating Documents."""
    docs = retrieve(query, top_k=top_k, rbac_context=rbac_context)
    authorized: list[Document] = []
    for doc in docs:
        meta = doc.metadata or {}
        if rbac_context.is_authorized(
            meta.get("tenant_id"),
            meta.get("access_groups") or meta.get("allowed_roles"),
            meta.get("classification"),
        ):
            authorized.append(doc)
    return [
        document_to_retrieval_result(doc, query_id=query_id, index=i)
        for i, doc in enumerate(authorized, 1)
    ]


def results_to_evidence(results: list[RetrievalResult]) -> list[Evidence]:
    evidence: list[Evidence] = []
    for i, result in enumerate(results, 1):
        evidence.append(
            retrieval_result_to_evidence(
                result,
                index=i,
                shown_to_generation=False,
            )
        )
    return evidence


def build_retrieval_plan(
    *,
    original_question: str,
    strategy: str,
    rbac_context: RBACContext,
    queries: list[tuple[str, str, int | None]] | None = None,
    top_k: int = 5,
) -> RetrievalPlan:
    """Build a RetrievalPlan from strategy and optional explicit queries."""
    tenant_id = rbac_context.tenant_id
    if queries:
        planned = tuple(
            PlannedQuery(text=text, purpose=purpose, hop_index=hop)
            for text, purpose, hop in queries
        )
    elif strategy == "decompose":
        from src.agents.decomposer import decompose_chain

        result = decompose_chain.invoke({"question": original_question})
        planned = tuple(
            PlannedQuery(text=sq, purpose="sub_query", hop_index=None)
            for sq in result.sub_queries
        ) or (PlannedQuery(text=original_question, purpose="primary"),)
    elif strategy == "multi_hop":
        planned = (PlannedQuery(text=original_question, purpose="hop_initial", hop_index=1),)
    else:
        planned = (PlannedQuery(text=original_question, purpose="primary"),)

    return RetrievalPlan(
        original_question=original_question,
        queries=planned,
        tenant_id=tenant_id,
        top_k=top_k,
        strategy=strategy,
    )


def execute_retrieval_plan(
    plan: RetrievalPlan,
    *,
    rbac_context: RBACContext,
) -> tuple[list[RetrievalResult], list[Evidence]]:
    """Execute all queries in a plan and return results + evidence candidates."""
    all_results: list[RetrievalResult] = []
    for query in plan.queries:
        hits = retrieve_candidates(
            query.text,
            query_id=query.query_id,
            rbac_context=rbac_context,
            top_k=plan.top_k,
        )
        all_results.extend(hits)
    return all_results, results_to_evidence(all_results)
