"""Canonical Agentic RAG LangGraph — parallel to legacy mode graphs."""

from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from src.agents.multi_hop import reflect_on_hop
from src.agents.query_rewriter import rewrite_query
from src.agents.router import RouteType
from src.chains.generation import rag_chain
from src.config import settings
from src.contracts.models import (
    AgentResponse,
    Evidence,
    PlannedQuery,
    RetrievalPlan,
    ToolResult,
    ToolStatus,
)
from src.graph.canonical_state import (
    CanonicalGraphState,
    CanonicalTimer,
    append_trace,
    graph_input,
    init_canonical_state,
    merge_state,
    read_graph_state,
    write_graph_state,
)
from src.graph.citation_mapper import map_citations
from src.graph.context_builder import build_generation_context
from src.graph.evidence_management import process_evidence_candidates
from src.graph.shared_nodes import invoke_router, run_direct_answer, run_web_search_answer
from src.graph.strategy_heuristics import select_strategy
from src.graph.verification_engine import (
    VerificationInput,
    apply_verification_outcome,
    derive_response_status,
    verify_response,
)
from src.canonical_observability.canonical_metrics import record_verification_outcome
from src.canonical_observability.canonical_timing import timed_node
from src.canonical_observability.canonical_tracing import canonical_span
from src.retrieval.canonical_adapter import (
    build_retrieval_plan,
    execute_retrieval_plan,
)
from src.schemas import RBACContext
from src.streaming import run_graph_streaming, stream_text

logger = logging.getLogger(__name__)

EMPTY_ANSWER = (
    "I couldn't find relevant documents in the knowledge base for this question."
)


def _read(raw: CanonicalGraphState):
    return read_graph_state(raw)


def _write(state):
    return write_graph_state(state)


def classify_node(raw: CanonicalGraphState) -> dict:
    state = _read(raw)
    try:
        route, reason = invoke_router(state.original_question)
    except Exception as exc:
        route, reason = RouteType.RETRIEVE.value, f"Router failed: {type(exc).__name__}"
        state = append_trace(
            merge_state(state, route=route, route_reason=reason),
            node="classify",
            event_type="route_selected",
            message="Router failed — defaulting to retrieve",
            metadata={"fallback": True, "error": type(exc).__name__},
        )
        return _write(state)

    state = append_trace(
        merge_state(state, route=route, route_reason=reason),
        node="classify",
        event_type="route_selected",
        message=f"Route={route}",
        metadata={"route": route, "reason": reason},
    )
    return _write(state)


def direct_answer_node(raw: CanonicalGraphState) -> dict:
    state = _read(raw)
    answer = run_direct_answer(state.original_question)
    state = append_trace(
        merge_state(
            state,
            answer=answer,
            llm_call_count=state.llm_call_count + 1,
        ),
        node="direct_answer",
        event_type="generation_completed",
        message="Direct answer generated",
    )
    return _write(state)


def strategy_select_node(raw: CanonicalGraphState) -> dict:
    state = _read(raw)
    forced = state.metadata.get("force_strategy")
    decision = select_strategy(
        state.original_question,
        force_strategy=forced,
    )
    llm_calls = state.llm_call_count + (1 if decision.decision_source == "llm" else 0)
    state = append_trace(
        merge_state(
            state,
            strategy=decision.strategy,
            strategy_reason=decision.rationale,
            strategy_decision_source=decision.decision_source,
            llm_call_count=llm_calls,
        ),
        node="strategy_select",
        event_type="strategy_selected",
        message=f"Strategy={decision.strategy}",
        metadata={
            "strategy": decision.strategy,
            "source": decision.decision_source,
            "confidence": decision.confidence,
        },
    )
    return _write(state)


def plan_retrieval_node(raw: CanonicalGraphState) -> dict:
    state = _read(raw)
    next_query = state.metadata.get("next_planned_query")
    if next_query:
        planned = (PlannedQuery(text=next_query, purpose="rewrite", hop_index=state.current_hop + 1),)
        plan = RetrievalPlan(
            original_question=state.original_question,
            queries=planned,
            tenant_id=state.tenant_id,
            strategy=state.strategy,
        )
    else:
        plan = build_retrieval_plan(
            original_question=state.original_question,
            strategy=state.strategy,
            rbac_context=state.rbac_context,
        )
    state = append_trace(
        merge_state(state, retrieval_plan=plan, search_query=plan.queries[0].text),
        node="plan_retrieval",
        event_type="retrieval_plan_created",
        message=f"Plan with {len(plan.queries)} queries",
        metadata={"query_count": len(plan.queries), "strategy": state.strategy},
    )
    return _write(state)


def retrieve_node(raw: CanonicalGraphState) -> dict:
    state = _read(raw)
    plan = state.retrieval_plan
    if plan is None:
        plan = build_retrieval_plan(
            original_question=state.original_question,
            strategy=state.strategy,
            rbac_context=state.rbac_context,
        )
    state = append_trace(
        state,
        node="retrieve",
        event_type="retrieval_started",
        message="Retrieval started",
    )
    results, candidates = execute_retrieval_plan(plan, rbac_context=state.rbac_context)
    state = append_trace(
        merge_state(
            state,
            retrieval_results=state.retrieval_results + tuple(results),
            evidence=tuple(candidates),
        ),
        node="retrieve",
        event_type="retrieval_completed",
        message=f"Retrieved {len(results)} results",
        metadata={"result_count": len(results)},
    )
    return _write(state)


def grade_node(raw: CanonicalGraphState) -> dict:
    state = _read(raw)
    candidates = list(state.evidence)
    graded = process_evidence_candidates(state.original_question, candidates)
    state = append_trace(
        merge_state(state, evidence=tuple(graded)),
        node="grade",
        event_type="evidence_graded",
        message=f"{len(graded)}/{len(candidates)} evidence after grading",
        metadata={"kept": len(graded), "input": len(candidates)},
    )
    return _write(state)


def rewrite_node(raw: CanonicalGraphState) -> dict:
    state = _read(raw)
    try:
        rewritten = rewrite_query(state.original_question, state.search_query)
        query = rewritten.query
        reason = rewritten.reason
    except Exception as exc:
        query = state.search_query
        reason = f"Rewrite failed: {type(exc).__name__}"
    state = append_trace(
        merge_state(
            state,
            search_query=query,
            retry_count=state.retry_count + 1,
            llm_call_count=state.llm_call_count + 1,
            metadata={**state.metadata, "next_planned_query": query, "rewrite_reason": reason},
        ),
        node="rewrite",
        event_type="retry_triggered",
        message=f"Rewrite attempt {state.retry_count + 1}",
        metadata={"new_query": query, "reason": reason},
    )
    return _write(state)


def reflect_node(raw: CanonicalGraphState) -> dict:
    state = _read(raw)
    context_items = [e for e in state.evidence if e.included_in_context or e.content]
    context = "\n".join(item.content for item in context_items[:5])
    hop_history = state.metadata.get("hop_history", "")
    reflection = reflect_on_hop(
        state.original_question,
        state.current_hop or 1,
        state.search_query,
        context,
        hop_history,
    )
    metadata = dict(state.metadata)
    if reflection.sufficient:
        metadata.pop("next_planned_query", None)
    elif reflection.next_search_query:
        metadata["next_planned_query"] = reflection.next_search_query
    metadata["hop_history"] = (
        hop_history
        + f"\nHop {state.current_hop or 1}: {reflection.intermediate_finding}"
    ).strip()
    state = append_trace(
        merge_state(
            state,
            current_hop=state.current_hop + 1,
            llm_call_count=state.llm_call_count + 1,
            metadata=metadata,
        ),
        node="reflect",
        event_type="hop_reflection",
        message=reflection.intermediate_finding,
        metadata={
            "sufficient": reflection.sufficient,
            "next_query": reflection.next_search_query,
            "hop": state.current_hop,
            "evidence_count": len(state.evidence),
        },
    )
    metadata_sufficient = reflection.sufficient
    new_meta = {
        **metadata,
        "reflection_sufficient": metadata_sufficient,
        "reflection_done": True,
    }
    state = merge_state(state, metadata=new_meta)
    return _write(state)


def context_node(raw: CanonicalGraphState) -> dict:
    state = _read(raw)
    context_text, numbered, excluded = build_generation_context(
        state.original_question,
        list(state.evidence),
    )
    generation_ids = tuple(item.evidence_id for item in numbered)
    all_evidence = numbered + excluded
    state = append_trace(
        merge_state(
            state,
            context_text=context_text,
            evidence=tuple(all_evidence),
            generation_evidence_ids=generation_ids,
        ),
        node="context",
        event_type="context_built",
        message=f"Context includes {len(numbered)} evidence items",
        metadata={
            "included": len(numbered),
            "excluded": len(excluded),
            "token_budget_excluded": sum(
                1 for item in excluded if item.excluded_reason == "token_budget"
            ),
        },
    )
    return _write(state)


def generate_node(raw: CanonicalGraphState) -> dict:
    state = _read(raw)
    if not state.context_text.strip():
        state = merge_state(state, answer=EMPTY_ANSWER)
        return _write(state)
    answer = stream_text(
        rag_chain,
        {"context": state.context_text, "question": state.original_question},
    )
    citations, unknown, _dup, _malformed, _zero = map_citations(
        answer,
        [e for e in state.evidence if e.included_in_context],
    )
    state = append_trace(
        merge_state(
            state,
            answer=answer,
            citations=tuple(citations),
            llm_call_count=state.llm_call_count + 1,
            metadata={**state.metadata, "unknown_citation_indexes": unknown},
        ),
        node="generate",
        event_type="generation_completed",
        message="Generated answer from context",
    )
    return _write(state)


def web_search_node(raw: CanonicalGraphState) -> dict:
    state = _read(raw)
    context, answer = run_web_search_answer(state.original_question)
    tool = ToolResult(
        tool_name="web_search",
        status=ToolStatus.SUCCESS if context else ToolStatus.EMPTY,
        output=context,
    )
    evidence: tuple[Evidence, ...] = ()
    if context:
        from src.contracts.conversions import retrieval_result_to_evidence
        from src.contracts.models import RetrievalResult

        web_result = RetrievalResult(
            query_id="web_search",
            chunk_id="web-1",
            content=context[:3000],
            source="web search",
            tenant_id=state.tenant_id,
            metadata={"source_type": "web"},
        )
        evidence = (
            retrieval_result_to_evidence(
                web_result,
                index=1,
                shown_to_generation=True,
            ).model_copy(
                update={"included_in_context": True, "context_position": 1}
            ),
        )
    state = append_trace(
        merge_state(
            state,
            answer=answer,
            tool_results=state.tool_results + (tool,),
            evidence=evidence,
            generation_evidence_ids=tuple(e.evidence_id for e in evidence),
            context_text=context,
            llm_call_count=state.llm_call_count + 2,
        ),
        node="web_search",
        event_type="generation_completed",
        message="Web search answer generated",
    )
    return _write(state)


def verify_node(raw: CanonicalGraphState) -> dict:
    state = _read(raw)
    context_evidence = [e for e in state.evidence if e.included_in_context]
    unknown = state.metadata.get("unknown_citation_indexes", [])
    with timed_node("verify"):
        verification = verify_response(
            VerificationInput(
                question=state.original_question,
                answer=state.answer,
                context_evidence=context_evidence,
                citations=list(state.citations),
                unknown_citation_indexes=list(unknown),
            )
        )
    record_verification_outcome(verification.outcome)
    answer = apply_verification_outcome(state.answer, verification)
    state = append_trace(
        merge_state(state, verification=verification, answer=answer),
        node="verify",
        event_type="verification_completed",
        message=f"Verification outcome={verification.outcome}",
        metadata={
            "outcome": verification.outcome,
            "confidence": verification.confidence,
            "abstained": verification.abstained,
        },
    )
    return _write(state)


def _generate_follow_ups_safe(question: str, answer: str, evidence: tuple) -> tuple[str, ...]:
    if not answer or not answer.strip():
        return ()
    try:
        from src.agents.followups import generate_follow_ups

        sources = []
        for item in evidence:
            if item.included_in_context and item.result.source:
                sources.append(item.result.source)
        follow_ups = generate_follow_ups(question, answer, sources=sources)
        return tuple(follow_ups or ())
    except Exception:
        logger.warning("Follow-up generation failed; continuing without follow-ups", exc_info=True)
        return ()


def finalize_node(raw: CanonicalGraphState) -> dict:
    state = _read(raw)
    follow_ups = _generate_follow_ups_safe(
        state.original_question,
        state.answer,
        state.evidence,
    )
    response_status = derive_response_status(
        state.verification,
        error_code=state.error_code,
    )
    state = append_trace(
        merge_state(
            state,
            follow_ups=follow_ups,
            metadata={**state.metadata, "response_status": response_status},
        ),
        node="finalize",
        event_type="response_finalized",
        message="Canonical response finalized",
        metadata={"response_status": response_status, "follow_up_count": len(follow_ups)},
    )
    return _write(state)


def abort_node(raw: CanonicalGraphState) -> dict:
    state = _read(raw)
    reason = state.abort_reason or "Insufficient evidence"
    state = append_trace(
        merge_state(
            state,
            abort=True,
            answer=EMPTY_ANSWER,
            error_code="canonical_abort",
        ),
        node="abort",
        event_type="aborted",
        message=reason,
    )
    return _write(state)


def route_after_classify(state: CanonicalGraphState) -> str:
    s = _read(state)
    if s.route == RouteType.DIRECT.value:
        return "direct_answer"
    if s.route == RouteType.WEB_SEARCH.value:
        return "web_search"
    return "strategy_select"


def route_after_grade(state: CanonicalGraphState) -> str:
    s = _read(state)
    if s.abort:
        return "abort"
    if s.evidence:
        if s.strategy == "multi_hop" and not s.metadata.get("reflection_done"):
            return "reflect"
        return "context"
    if s.retry_count < settings.max_retrieval_retries:
        return "rewrite"
    return "web_fallback"


def route_after_rewrite(state: CanonicalGraphState) -> str:
    return "plan_retrieval"


def route_after_reflect(state: CanonicalGraphState) -> str:
    s = _read(state)
    if s.metadata.get("reflection_sufficient"):
        return "context"
    if s.current_hop >= settings.max_multi_hop_steps:
        return "context" if s.evidence else "abort"
    if s.metadata.get("next_planned_query"):
        return "plan_retrieval"
    return "context" if s.evidence else "abort"


def route_after_context(state: CanonicalGraphState) -> str:
    s = _read(state)
    return "generate" if s.context_text.strip() else "abort"


def build_canonical_graph():
    graph = StateGraph(CanonicalGraphState)
    graph.add_node("classify", classify_node)
    graph.add_node("direct_answer", direct_answer_node)
    graph.add_node("web_search", web_search_node)
    graph.add_node("strategy_select", strategy_select_node)
    graph.add_node("plan_retrieval", plan_retrieval_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("grade", grade_node)
    graph.add_node("rewrite", rewrite_node)
    graph.add_node("reflect", reflect_node)
    graph.add_node("context", context_node)
    graph.add_node("generate", generate_node)
    graph.add_node("verify", verify_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("abort", abort_node)
    graph.add_node("web_fallback", web_search_node)

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        route_after_classify,
        {
            "direct_answer": "direct_answer",
            "web_search": "web_search",
            "strategy_select": "strategy_select",
        },
    )
    graph.add_edge("direct_answer", "verify")
    graph.add_edge("web_search", "verify")
    graph.add_edge("strategy_select", "plan_retrieval")
    graph.add_edge("plan_retrieval", "retrieve")
    graph.add_edge("retrieve", "grade")
    graph.add_conditional_edges(
        "grade",
        route_after_grade,
        {
            "context": "context",
            "rewrite": "rewrite",
            "reflect": "reflect",
            "web_fallback": "web_fallback",
            "abort": "abort",
        },
    )
    graph.add_edge("rewrite", "plan_retrieval")
    graph.add_conditional_edges(
        "reflect",
        route_after_reflect,
        {
            "context": "context",
            "plan_retrieval": "plan_retrieval",
            "abort": "abort",
        },
    )
    graph.add_conditional_edges(
        "context",
        route_after_context,
        {"generate": "generate", "abort": "abort"},
    )
    graph.add_edge("generate", "verify")
    graph.add_edge("verify", "finalize")
    graph.add_edge("finalize", END)
    graph.add_edge("abort", END)
    graph.add_edge("web_fallback", "verify")

    # Multi-hop reflect path: after grade when strategy is multi_hop and not sufficient
    # wired via metadata in grade condition - simplified: reflect inserted manually in tests

    return graph.compile()


_canonical_graph = None


def get_canonical_graph():
    global _canonical_graph
    if _canonical_graph is None:
        _canonical_graph = build_canonical_graph()
    return _canonical_graph


def _to_canonical_response(state, timer: CanonicalTimer) -> AgentResponse:
    response_status = state.metadata.get("response_status") or derive_response_status(
        state.verification,
        error_code=state.error_code,
    )
    return AgentResponse(
        answer=state.answer,
        mode=state.mode,
        route=state.route,
        strategy=state.strategy,
        evidence=state.evidence,
        citations=state.citations,
        verification=state.verification,
        trace=state.trace,
        follow_ups=state.follow_ups,
        tenant_id=state.tenant_id,
        error_code=state.error_code,
        latency_ms=timer.elapsed_ms(),
        response_status=response_status,
    )


def to_legacy_adapter(canonical: AgentResponse):
    """Deprecated — use src.contracts.api_response.canonical_to_api_response."""
    from src.contracts.api_response import canonical_to_api_response

    return canonical_to_api_response(canonical, display_mode=canonical.mode or "canonical")


def ask_canonical(
    question: str,
    *,
    rbac_context: RBACContext | None = None,
    force_strategy: str | None = None,
) -> AgentResponse:
    """Run the canonical graph (development / test path only)."""
    timer = CanonicalTimer()
    metadata = {}
    if force_strategy:
        metadata["force_strategy"] = force_strategy
    state = init_canonical_state(
        question,
        rbac_context=rbac_context,
        mode="canonical",
        strategy_override=force_strategy,
    )
    if metadata:
        state = merge_state(state, metadata=metadata)
    graph = get_canonical_graph()
    request_id = state.trace[0].event_id if state.trace else "unknown"
    with canonical_span(
        "canonical.request",
        attributes={
            "request_id": request_id,
            "tenant_id": state.tenant_id,
            "route": state.route or "",
            "strategy": state.strategy or "",
        },
    ):
        result = run_graph_streaming(graph, graph_input(state))
    final = read_graph_state(result)
    final = merge_state(final, latency_ms=timer.elapsed_ms())
    return _to_canonical_response(final, timer)
