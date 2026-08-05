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
from src.retrieval.retriever import format_docs, retrieve
from src.schemas import AgentResponse
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


def classify_node(state: CRAGState) -> dict:
    """Route the question (Phase 2 router_chain)."""
    decision = router_chain.invoke({"question": state["question"]})
    return {
        "route": decision.route.value,
        "route_reason": decision.reason,
        "search_query": state["question"],
        "steps": [f"Router → {decision.route.value}: {decision.reason}"],
    }


def direct_answer_node(state: CRAGState) -> dict:
    answer = direct_chain.invoke({"question": state["question"]})
    return {"answer": answer, "sources": [], "steps": ["Direct answer (no retrieval)"]}


def retrieve_node(state: CRAGState) -> dict:
    """Retrieve using the current search query (original or rewritten)."""
    docs = retrieve(state["search_query"])
    sources = list({doc.metadata.get("source", "unknown") for doc in docs})
    attempt = state["retry_count"] + 1
    return {
        "documents": docs,
        "sources": sources,
        "steps": [f"Retrieval attempt {attempt}: fetched {len(docs)} chunks for '{state['search_query']}'"],
    }


def grade_node(state: CRAGState) -> dict:
    """Grade documents and keep only relevant chunks."""
    filtered, result = grade_documents(state["question"], state["documents"])
    summary = summarize_grades(result)
    return {
        "filtered_documents": filtered,
        "grade_summary": summary,
        "steps": [f"Grader: {summary}"],
    }


def rewrite_node(state: CRAGState) -> dict:
    """Rewrite the search query for another retrieval attempt."""
    rewritten = rewrite_query(state["question"], state["search_query"])
    return {
        "search_query": rewritten.query,
        "retry_count": state["retry_count"] + 1,
        "steps": [f"Query rewrite (attempt {state['retry_count'] + 2}): {rewritten.reason}"],
    }


def generate_node(state: CRAGState) -> dict:
    """Generate using only grader-approved documents."""
    context = format_docs(state["filtered_documents"])
    answer = rag_chain.invoke({"context": context, "question": state["question"]})
    return {
        "answer": answer,
        "steps": [f"Generated answer from {len(state['filtered_documents'])} relevant chunks"],
    }


def web_fallback_node(state: CRAGState) -> dict:
    """CRAG fallback: web search when knowledge base retrieval fails."""
    context = web_search.invoke(state["question"])
    answer = web_search_chain.invoke({"context": context, "question": state["question"]})
    return {
        "web_context": context,
        "answer": answer,
        "sources": ["web search (CRAG fallback)"],
        "steps": ["CRAG fallback → web search (no relevant docs after retries)"],
    }


def route_condition(state: CRAGState) -> Literal["direct", "retrieve", "web_search"]:
    return state["route"]  # type: ignore[return-value]


def grade_condition(state: CRAGState) -> Literal["generate", "rewrite", "web_fallback"]:
    """Decide next step after grading."""
    if state["filtered_documents"]:
        return "generate"
    if state["retry_count"] < settings.max_retrieval_retries:
        return "rewrite"
    return "web_fallback"


def build_crag_graph():
    graph = StateGraph(CRAGState)

    graph.add_node("classify", classify_node)
    graph.add_node("direct_answer", direct_answer_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("grade", grade_node)
    graph.add_node("rewrite", rewrite_node)
    graph.add_node("generate", generate_node)
    graph.add_node("web_fallback", web_fallback_node)

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        route_condition,
        {
            RouteType.DIRECT.value: "direct_answer",
            RouteType.RETRIEVE.value: "retrieve",
            RouteType.WEB_SEARCH.value: "web_fallback",
        },
    )
    graph.add_edge("direct_answer", END)
    graph.add_edge("retrieve", "grade")
    graph.add_conditional_edges(
        "grade",
        grade_condition,
        {
            "generate": "generate",
            "rewrite": "rewrite",
            "web_fallback": "web_fallback",
        },
    )
    graph.add_edge("rewrite", "retrieve")
    graph.add_edge("generate", END)
    graph.add_edge("web_fallback", END)

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
    result = graph.invoke(
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
        }
    )
    return AgentResponse(
        answer=result["answer"],
        mode="crag",
        sources=result.get("sources", []),
        route=result.get("route"),
        route_reason=result.get("route_reason"),
        grade_summary=result.get("grade_summary") or None,
        steps=result.get("steps", []),
    )
