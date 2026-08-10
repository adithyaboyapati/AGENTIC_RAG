"""
Phase 7: Full Agentic RAG — StateGraph combining all patterns.

Flow:
  classify → choose_strategy → [decompose | multi_hop | tools | simple]
                                      ↓
                                   grade
                                      ↓
                              [generate | rewrite | fallback]
                                      ↓
                                    END

All retrieval strategies pass through CRAG grading before the final answer.
Node-level output gates contain poison / critical failures.
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from langchain_core.documents import Document
from langgraph.graph import END, START, StateGraph

from src.agents.grader import grade_documents, summarize_grades
from src.agents.orchestrator import choose_strategy, normalize_strategy
from src.agents.query_rewriter import rewrite_query
from src.agents.router import RouteType, router_chain
from src.chains.generation import direct_chain, rag_chain, web_search_chain
from src.config import settings
from src.resilience.node_gate import (
    abort_user_message,
    check_answer,
    check_route,
    check_strategy,
    check_web_context,
)
from src.retrieval.citations import build_response, docs_to_sources
from src.retrieval.retriever import format_docs, retrieve
from src.schemas import AgentResponse
from src.streaming import (
    emit_token,
    get_emitter,
    run_graph_streaming,
    stream_text,
    suppress_token_emit,
)
from src.tools.web_search import web_search


class AgentState(TypedDict):
    question: str
    route: str
    route_reason: str
    strategy: str
    strategy_reason: str
    documents: list[Document]
    filtered_documents: list[Document]
    grade_summary: str
    retry_count: int
    answer: str
    sources: list[str]
    steps: Annotated[list[str], operator.add]
    abort: bool
    abort_reason: str


def classify_node(state: AgentState) -> dict:
    """Route: direct, retrieve, or web."""
    try:
        decision = router_chain.invoke({"question": state["question"]})
        route = decision.route.value
        reason = decision.reason
    except Exception as exc:
        return {
            "abort": True,
            "abort_reason": f"Router failed: {type(exc).__name__}",
            "steps": [f"Node gate abort [router_exception]: {type(exc).__name__}"],
        }

    gate = check_route(route)
    if not gate.ok:
        return {
            "abort": True,
            "abort_reason": gate.message,
            "route": route,
            "route_reason": reason,
            "steps": [f"Node gate abort [{gate.code}]: {gate.message}"],
        }

    return {
        "route": route,
        "route_reason": reason,
        "steps": [f"Router → {route}: {reason}"],
    }


def strategy_node(state: AgentState) -> dict:
    """Choose best retrieval strategy: decompose, multi_hop, tools, or simple."""
    if state.get("abort"):
        return {}
    try:
        choice = choose_strategy(state["question"])
        strategy = normalize_strategy(choice.strategy)
        reason = choice.reasoning
    except Exception as exc:
        return {
            "abort": True,
            "abort_reason": f"Strategy selection failed: {type(exc).__name__}",
            "steps": [f"Node gate abort [strategy_exception]: {type(exc).__name__}"],
        }

    gate = check_strategy(strategy)
    if not gate.ok:
        return {
            "abort": True,
            "abort_reason": gate.message,
            "strategy": strategy,
            "strategy_reason": reason,
            "steps": [f"Node gate abort [{gate.code}]: {gate.message}"],
        }

    return {
        "strategy": strategy,
        "strategy_reason": reason,
        "steps": [f"Strategy: {strategy} — {reason}"],
    }


def direct_answer_node(state: AgentState) -> dict:
    if state.get("abort"):
        return {}
    answer = stream_text(direct_chain, {"question": state["question"]})
    gate = check_answer(answer, required=True)
    if not gate.ok:
        return {
            "abort": True,
            "abort_reason": gate.message,
            "answer": "",
            "sources": [],
            "documents": [],
            "steps": [f"Node gate abort [{gate.code}]: {gate.message}"],
        }
    return {
        "answer": answer,
        "sources": [],
        "documents": [],
        "steps": ["Direct answer (no retrieval)"],
    }


def web_search_node(state: AgentState) -> dict:
    if state.get("abort"):
        return {}
    context = web_search.invoke(state["question"])
    ctx_gate = check_web_context(str(context) if context is not None else "")
    if not ctx_gate.ok:
        return {
            "abort": True,
            "abort_reason": ctx_gate.message,
            "answer": "",
            "sources": [],
            "documents": [],
            "steps": [
                f"Node gate abort [{ctx_gate.code}]: web path blocked — {ctx_gate.message}"
            ],
        }
    answer = stream_text(
        web_search_chain, {"context": context, "question": state["question"]}
    )
    ans_gate = check_answer(answer, required=True)
    if not ans_gate.ok:
        return {
            "abort": True,
            "abort_reason": ans_gate.message,
            "answer": "",
            "sources": [],
            "documents": [],
            "steps": [f"Node gate abort [{ans_gate.code}]: {ans_gate.message}"],
        }
    return {
        "answer": answer,
        "sources": ["web search"],
        "documents": [],
        "steps": ["Web search + generated answer"],
    }


def decompose_node(state: AgentState) -> dict:
    """Decompose into parallel sub-queries (documents graded next)."""
    if state.get("abort"):
        return {}
    from src.graph.decompose_graph import get_decompose_graph

    graph = get_decompose_graph()
    with suppress_token_emit():
        result = graph.invoke(
            {
                "question": state["question"],
                "route": RouteType.RETRIEVE.value,
                "route_reason": state["route_reason"],
                "skip_router": True,
                "sub_queries": [],
                "decomposition_reason": "",
                "sub_results": [],
                "answer": "",
                "sources": [],
                "steps": [],
            }
        )
    docs = [doc for sub in result.get("sub_results", []) for doc in sub["documents"]]
    return {
        "documents": docs,
        "answer": result.get("answer", ""),
        "sources": docs_to_sources(docs) or result.get("sources", []),
        "steps": [
            f"Decomposed into {len(result.get('sub_results', []))} sub-queries "
            f"({len(docs)} chunks) — grading next"
        ],
    }


def multi_hop_node(state: AgentState) -> dict:
    """Sequential multi-hop retrieval (documents graded next)."""
    if state.get("abort"):
        return {}
    from src.graph.multi_hop_graph import get_multi_hop_graph

    graph = get_multi_hop_graph()
    with suppress_token_emit():
        result = graph.invoke(
            {
                "question": state["question"],
                "route": RouteType.RETRIEVE.value,
                "route_reason": state["route_reason"],
                "skip_router": True,
                "needs_multi_hop": True,
                "multi_hop_reason": "",
                "current_hop": 0,
                "search_query": "",
                "sufficient": False,
                "hop_results": [],
                "answer": "",
                "sources": [],
                "steps": [],
            }
        )
    docs = [doc for hop in result.get("hop_results", []) for doc in hop["documents"]]
    return {
        "documents": docs,
        "answer": result.get("answer", ""),
        "sources": docs_to_sources(docs) or result.get("sources", []),
        "steps": [
            f"Multi-hop: {len(result.get('hop_results', []))} sequential retrievals "
            f"({len(docs)} chunks) — grading next"
        ],
    }


def tools_node(state: AgentState) -> dict:
    """Tool-calling agent; retrieved docs are graded when present."""
    if state.get("abort"):
        return {}
    from src.graph.tools_graph import get_tools_graph

    graph = get_tools_graph()
    with suppress_token_emit():
        result = graph.invoke(
            {
                "question": state["question"],
                "route": RouteType.RETRIEVE.value,
                "route_reason": state["route_reason"],
                "skip_router": True,
                "messages": [],
                "documents": [],
                "answer": "",
                "sources": [],
                "steps": [],
                "abort": False,
                "abort_reason": "",
            }
        )
    if result.get("abort"):
        return {
            "abort": True,
            "abort_reason": result.get("abort_reason") or "Tools subgraph aborted",
            "documents": [],
            "answer": "",
            "sources": [],
            "steps": [
                f"Tools subgraph abort: {result.get('abort_reason') or 'unknown'}"
            ],
        }
    docs = result.get("documents") or []
    return {
        "documents": docs,
        "answer": result.get("answer", ""),
        "sources": result.get("sources", []),
        "steps": [
            f"Tool-augmented: {len(result.get('steps', []))} steps, "
            f"{len(docs)} retrieved chunks — grading next"
        ],
    }


def simple_retrieve_node(state: AgentState) -> dict:
    """Simple single-pass retrieval."""
    if state.get("abort"):
        return {}
    docs = retrieve(state["question"])
    return {
        "documents": docs,
        "sources": docs_to_sources(docs),
        "steps": [f"Simple retrieval: fetched {len(docs)} chunks"],
    }


def grade_node(state: AgentState) -> dict:
    """Grade documents (CRAG safety net for every strategy)."""
    if state.get("abort"):
        return {}
    if not state["documents"]:
        return {
            "filtered_documents": [],
            "grade_summary": "No documents to grade",
            "steps": ["Grader: No documents"],
        }
    try:
        filtered, result = grade_documents(state["question"], state["documents"])
        summary = summarize_grades(result)
    except Exception as exc:
        return {
            "abort": True,
            "abort_reason": f"Grader failed: {type(exc).__name__}",
            "filtered_documents": [],
            "steps": [f"Node gate abort [grader_exception]: {type(exc).__name__}"],
        }
    return {
        "filtered_documents": filtered,
        "grade_summary": summary,
        "sources": docs_to_sources(filtered) if filtered else state.get("sources", []),
        "steps": [f"Grader: {summary}"],
    }


def generate_node(state: AgentState) -> dict:
    """Generate from graded documents when available."""
    if state.get("abort"):
        return {}
    if state["filtered_documents"]:
        context = format_docs(state["filtered_documents"])
        answer = stream_text(
            rag_chain, {"context": context, "question": state["question"]}
        )
        gate = check_answer(answer, required=True)
        if not gate.ok:
            return {
                "abort": True,
                "abort_reason": gate.message,
                "answer": "",
                "steps": [f"Node gate abort [{gate.code}]: {gate.message}"],
            }
        return {
            "answer": answer,
            "steps": [f"Generated from {len(state['filtered_documents'])} relevant chunks"],
        }

    # Tools/web may already have an answer with no corpus docs
    prior = state.get("answer") or ""
    if prior:
        gate = check_answer(prior, required=True)
        if not gate.ok:
            return {
                "abort": True,
                "abort_reason": gate.message,
                "answer": "",
                "steps": [f"Node gate abort [{gate.code}]: prior strategy answer invalid"],
            }
        if get_emitter() is not None:
            emit_token(prior)
        return {
            "answer": prior,
            "steps": ["Kept prior strategy answer (no graded corpus chunks)"],
        }
    return {
        "abort": True,
        "abort_reason": "No graded documents and no prior answer",
        "answer": "",
        "steps": ["Node gate abort [docs_required]: no graded documents and no prior answer"],
    }


def rewrite_node(state: AgentState) -> dict:
    """Rewrite query and retry."""
    if state.get("abort"):
        return {}
    try:
        rewritten = rewrite_query(state["question"], state["question"])
        query = rewritten.query
        reason = rewritten.reason
    except Exception as exc:
        return {
            "abort": True,
            "abort_reason": f"Query rewrite failed: {type(exc).__name__}",
            "steps": [f"Node gate abort [rewrite_exception]: {type(exc).__name__}"],
        }
    if not (query or "").strip():
        return {
            "abort": True,
            "abort_reason": "Query rewrite produced an empty search query",
            "steps": ["Node gate abort [empty_rewrite]: rewritten query was empty"],
        }
    new_docs = retrieve(query)
    return {
        "documents": new_docs,
        "sources": docs_to_sources(new_docs),
        "retry_count": state["retry_count"] + 1,
        "steps": [f"Query rewrite (attempt {state['retry_count'] + 2}): {reason}"],
    }


def fallback_node(state: AgentState) -> dict:
    """Web fallback when retrieval fails."""
    if state.get("abort"):
        return {}
    # Prefer a prior tools answer over web if one exists
    prior = state.get("answer") or ""
    if prior and state.get("strategy") == "tools":
        gate = check_answer(prior, required=True)
        if not gate.ok:
            return {
                "abort": True,
                "abort_reason": gate.message,
                "answer": "",
                "steps": [f"Node gate abort [{gate.code}]: tools answer invalid after empty grade"],
            }
        return {
            "answer": prior,
            "steps": ["Kept tools answer after empty grade (no web fallback)"],
        }
    context = web_search.invoke(state["question"])
    ctx_gate = check_web_context(str(context) if context is not None else "")
    if not ctx_gate.ok:
        return {
            "abort": True,
            "abort_reason": ctx_gate.message,
            "answer": "",
            "sources": [],
            "filtered_documents": [],
            "steps": [
                f"Node gate abort [{ctx_gate.code}]: web fallback blocked — {ctx_gate.message}"
            ],
        }
    answer = stream_text(
        web_search_chain, {"context": context, "question": state["question"]}
    )
    ans_gate = check_answer(answer, required=True)
    if not ans_gate.ok:
        return {
            "abort": True,
            "abort_reason": ans_gate.message,
            "answer": "",
            "sources": [],
            "filtered_documents": [],
            "steps": [f"Node gate abort [{ans_gate.code}]: {ans_gate.message}"],
        }
    return {
        "answer": answer,
        "sources": ["web search (fallback)"],
        "filtered_documents": [],
        "steps": ["Fallback: web search (docs insufficient)"],
    }


def abort_node(state: AgentState) -> dict:
    reason = state.get("abort_reason") or "a required step failed"
    return {
        "answer": abort_user_message(reason),
        "sources": [],
        "documents": [],
        "filtered_documents": [],
        "steps": [f"Aborted: {reason}"],
    }


def route_condition(
    state: AgentState,
) -> Literal["direct", "retrieve", "web_search", "abort"]:
    if state.get("abort"):
        return "abort"
    if state["route"] == RouteType.DIRECT.value:
        return "direct"
    if state["route"] == RouteType.WEB_SEARCH.value:
        return "web_search"
    if state["route"] == RouteType.RETRIEVE.value:
        return "retrieve"
    return "abort"


def strategy_condition(
    state: AgentState,
) -> Literal["decompose", "multi_hop", "tools", "simple", "abort"]:
    if state.get("abort"):
        return "abort"
    return normalize_strategy(state.get("strategy"))  # type: ignore[return-value]


def grade_condition(
    state: AgentState,
) -> Literal["generate", "rewrite", "fallback", "abort"]:
    if state.get("abort"):
        return "abort"
    if state["filtered_documents"]:
        return "generate"
    # Tools without corpus hits: keep tool answer via generate/fallback special cases
    if state.get("strategy") == "tools" and state.get("answer"):
        return "generate"
    if state["retry_count"] < settings.max_retrieval_retries:
        return "rewrite"
    return "fallback"


def after_node_condition(state: AgentState) -> Literal["abort", "end"]:
    return "abort" if state.get("abort") else "end"


def build_full_agent_graph():
    graph = StateGraph(AgentState)

    graph.add_node("classify", classify_node)
    graph.add_node("strategy", strategy_node)
    graph.add_node("direct_answer", direct_answer_node)
    graph.add_node("web_search", web_search_node)
    graph.add_node("decompose", decompose_node)
    graph.add_node("multi_hop", multi_hop_node)
    graph.add_node("tools", tools_node)
    graph.add_node("simple_retrieve", simple_retrieve_node)
    graph.add_node("grade", grade_node)
    graph.add_node("generate", generate_node)
    graph.add_node("rewrite", rewrite_node)
    graph.add_node("fallback", fallback_node)
    graph.add_node("abort", abort_node)

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        route_condition,
        {
            "direct": "direct_answer",
            "retrieve": "strategy",
            "web_search": "web_search",
            "abort": "abort",
        },
    )
    graph.add_conditional_edges(
        "direct_answer",
        after_node_condition,
        {"abort": "abort", "end": END},
    )
    graph.add_conditional_edges(
        "web_search",
        after_node_condition,
        {"abort": "abort", "end": END},
    )
    graph.add_conditional_edges(
        "strategy",
        strategy_condition,
        {
            "decompose": "decompose",
            "multi_hop": "multi_hop",
            "tools": "tools",
            "simple": "simple_retrieve",
            "abort": "abort",
        },
    )
    # All retrieval strategies go through CRAG grading
    graph.add_edge("decompose", "grade")
    graph.add_edge("multi_hop", "grade")
    graph.add_edge("tools", "grade")
    graph.add_edge("simple_retrieve", "grade")
    graph.add_conditional_edges(
        "grade",
        grade_condition,
        {
            "generate": "generate",
            "rewrite": "rewrite",
            "fallback": "fallback",
            "abort": "abort",
        },
    )
    graph.add_conditional_edges(
        "generate",
        after_node_condition,
        {"abort": "abort", "end": END},
    )
    graph.add_edge("rewrite", "grade")
    graph.add_conditional_edges(
        "fallback",
        after_node_condition,
        {"abort": "abort", "end": END},
    )
    graph.add_edge("abort", END)

    return graph.compile()


_agent_graph = None


def get_full_agent_graph():
    global _agent_graph
    if _agent_graph is None:
        _agent_graph = build_full_agent_graph()
    return _agent_graph


def ask_agentic(question: str) -> AgentResponse:
    """Run the Phase 7 full agentic RAG agent."""
    graph = get_full_agent_graph()
    result = run_graph_streaming(
        graph,
        {
            "question": question,
            "route": "",
            "route_reason": "",
            "strategy": "",
            "strategy_reason": "",
            "documents": [],
            "filtered_documents": [],
            "grade_summary": "",
            "retry_count": 0,
            "answer": "",
            "sources": [],
            "steps": [],
            "abort": False,
            "abort_reason": "",
        },
    )
    error_code = "node_gate_abort" if result.get("abort") else None
    answer = result.get("answer") or ""
    if result.get("abort") and not answer:
        answer = abort_user_message(result.get("abort_reason"))
    docs = result.get("filtered_documents") or result.get("documents") or []
    return build_response(
        answer=answer,
        mode="agentic",
        docs=[] if error_code else docs,
        sources=[] if error_code else result.get("sources", []),
        route=result.get("route"),
        route_reason=result.get("route_reason"),
        decomposition_reason=result.get("strategy_reason"),
        grade_summary=result.get("grade_summary"),
        steps=result.get("steps", []),
        error_code=error_code,
    )
