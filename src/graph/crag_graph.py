"""
Phase 3: Corrective RAG (CRAG) — LangGraph agent.

Builds on Phase 2 routing and adds a corrective retrieval loop:
  retrieve → grade → [generate | rewrite → retrieve | web fallback]

Uses LangGraph for the loop and LangChain chains/tools inside each node.
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from langchain_core.documents import Document
from langgraph.graph import END, START, StateGraph

from src.agents.grader import grade_documents, summarize_grades
from src.agents.query_rewriter import rewrite_query
from src.agents.router import RouteType, router_chain
from src.chains.generation import direct_chain, rag_chain, web_search_chain
from src.config import settings
from src.resilience.node_gate import (
    abort_user_message,
    check_answer,
    check_route,
    check_web_context,
)
from src.retrieval.citations import build_response, docs_to_sources
from src.retrieval.retriever import format_docs, retrieve
from src.schemas import AgentResponse
from src.streaming import run_graph_streaming, stream_text
from src.tools.web_search import web_search


class CRAGState(TypedDict):
    question: str
    search_query: str
    route: str
    route_reason: str
    documents: list[Document]
    filtered_documents: list[Document]
    retry_count: int
    grade_summary: str
    answer: str
    sources: list[str]
    web_context: str
    steps: Annotated[list[str], operator.add]
    abort: bool
    abort_reason: str


def classify_node(state: CRAGState) -> dict:
    """Route the question (Phase 2 router_chain)."""
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
        "search_query": state["question"],
        "steps": [f"Router → {route}: {reason}"],
    }


def direct_answer_node(state: CRAGState) -> dict:
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
            "filtered_documents": [],
            "steps": [f"Node gate abort [{gate.code}]: {gate.message}"],
        }
    return {
        "answer": answer,
        "sources": [],
        "filtered_documents": [],
        "steps": ["Direct answer (no retrieval)"],
    }


def retrieve_node(state: CRAGState) -> dict:
    """Retrieve using the current search query (original or rewritten)."""
    if state.get("abort"):
        return {}
    docs = retrieve(state["search_query"])
    attempt = state["retry_count"] + 1
    return {
        "documents": docs,
        "sources": docs_to_sources(docs),
        "steps": [
            f"Retrieval attempt {attempt}: fetched {len(docs)} chunks for '{state['search_query']}'"
        ],
    }


def grade_node(state: CRAGState) -> dict:
    """Grade documents and keep only relevant chunks."""
    if state.get("abort"):
        return {}
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


def rewrite_node(state: CRAGState) -> dict:
    """Rewrite the search query for another retrieval attempt."""
    if state.get("abort"):
        return {}
    try:
        rewritten = rewrite_query(state["question"], state["search_query"])
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
    return {
        "search_query": query,
        "retry_count": state["retry_count"] + 1,
        "steps": [f"Query rewrite (attempt {state['retry_count'] + 2}): {reason}"],
    }


def generate_node(state: CRAGState) -> dict:
    """Generate using only grader-approved documents."""
    if state.get("abort"):
        return {}
    if not state.get("filtered_documents"):
        return {
            "abort": True,
            "abort_reason": "Generate called without graded documents",
            "answer": "",
            "steps": ["Node gate abort [docs_required]: no graded documents for generation"],
        }
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
        "steps": [f"Generated answer from {len(state['filtered_documents'])} relevant chunks"],
    }


def web_fallback_node(state: CRAGState) -> dict:
    """CRAG fallback: web search when knowledge base retrieval fails."""
    if state.get("abort"):
        return {}
    context = web_search.invoke(state["question"])
    ctx_gate = check_web_context(str(context) if context is not None else "")
    if not ctx_gate.ok:
        return {
            "abort": True,
            "abort_reason": ctx_gate.message,
            "web_context": "",
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
            "web_context": "",
            "answer": "",
            "sources": [],
            "filtered_documents": [],
            "steps": [f"Node gate abort [{ans_gate.code}]: {ans_gate.message}"],
        }
    return {
        "web_context": context,
        "answer": answer,
        "sources": ["web search (CRAG fallback)"],
        "filtered_documents": [],
        "steps": ["CRAG fallback → web search (no relevant docs after retries)"],
    }


def abort_node(state: CRAGState) -> dict:
    reason = state.get("abort_reason") or "a required step failed"
    return {
        "answer": abort_user_message(reason),
        "sources": [],
        "filtered_documents": [],
        "web_context": "",
        "steps": [f"Aborted: {reason}"],
    }


def route_condition(
    state: CRAGState,
) -> Literal["direct", "retrieve", "web_search", "abort"]:
    if state.get("abort"):
        return "abort"
    route = state.get("route") or ""
    if route == RouteType.DIRECT.value:
        return "direct"
    if route == RouteType.WEB_SEARCH.value:
        return "web_search"
    if route == RouteType.RETRIEVE.value:
        return "retrieve"
    return "abort"


def grade_condition(
    state: CRAGState,
) -> Literal["generate", "rewrite", "web_fallback", "abort"]:
    """Decide next step after grading."""
    if state.get("abort"):
        return "abort"
    if state["filtered_documents"]:
        return "generate"
    if state["retry_count"] < settings.max_retrieval_retries:
        return "rewrite"
    return "web_fallback"


def after_node_condition(state: CRAGState) -> Literal["abort", "end"]:
    return "abort" if state.get("abort") else "end"


def build_crag_graph():
    graph = StateGraph(CRAGState)

    graph.add_node("classify", classify_node)
    graph.add_node("direct_answer", direct_answer_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("grade", grade_node)
    graph.add_node("rewrite", rewrite_node)
    graph.add_node("generate", generate_node)
    graph.add_node("web_fallback", web_fallback_node)
    graph.add_node("abort", abort_node)

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        route_condition,
        {
            "direct": "direct_answer",
            "retrieve": "retrieve",
            "web_search": "web_fallback",
            "abort": "abort",
        },
    )
    graph.add_conditional_edges(
        "direct_answer",
        after_node_condition,
        {"abort": "abort", "end": END},
    )
    graph.add_edge("retrieve", "grade")
    graph.add_conditional_edges(
        "grade",
        grade_condition,
        {
            "generate": "generate",
            "rewrite": "rewrite",
            "web_fallback": "web_fallback",
            "abort": "abort",
        },
    )
    graph.add_edge("rewrite", "retrieve")
    graph.add_conditional_edges(
        "generate",
        after_node_condition,
        {"abort": "abort", "end": END},
    )
    graph.add_conditional_edges(
        "web_fallback",
        after_node_condition,
        {"abort": "abort", "end": END},
    )
    graph.add_edge("abort", END)

    return graph.compile()


_crag_graph = None


def get_crag_graph():
    global _crag_graph
    if _crag_graph is None:
        _crag_graph = build_crag_graph()
    return _crag_graph


def ask_crag(question: str) -> AgentResponse:
    """Run the Phase 3 Corrective RAG agent."""
    graph = get_crag_graph()
    result = run_graph_streaming(
        graph,
        {
            "question": question,
            "search_query": question,
            "route": "",
            "route_reason": "",
            "documents": [],
            "filtered_documents": [],
            "retry_count": 0,
            "grade_summary": "",
            "answer": "",
            "sources": [],
            "web_context": "",
            "steps": [],
            "abort": False,
            "abort_reason": "",
        },
    )
    error_code = "node_gate_abort" if result.get("abort") else None
    answer = result.get("answer") or ""
    if result.get("abort") and not answer:
        answer = abort_user_message(result.get("abort_reason"))

    docs = result.get("filtered_documents") or []
    context_docs = [d.page_content for d in docs]
    if result.get("web_context") and not error_code:
        context_docs = [result["web_context"]]

    return build_response(
        answer=answer,
        mode="crag",
        docs=[] if error_code else docs,
        sources=[] if error_code else result.get("sources", []),
        context_docs=[] if error_code else context_docs,
        route=result.get("route"),
        route_reason=result.get("route_reason"),
        grade_summary=result.get("grade_summary") or None,
        steps=result.get("steps", []),
        error_code=error_code,
    )
