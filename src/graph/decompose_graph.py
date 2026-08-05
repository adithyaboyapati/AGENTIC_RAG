"""
Phase 4: Query Decomposition — LangGraph map-reduce agent.

Flow:
  classify → [direct | web | decompose → parallel retrieve → synthesize]

Uses LangGraph Send API for parallel sub-query retrieval (map-reduce pattern).
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from langchain_core.documents import Document
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from src.agents.decomposer import decompose_chain
from src.agents.router import RouteType, router_chain
from src.chains.generation import direct_chain, synthesis_chain, web_search_chain
from src.retrieval.retriever import format_docs, retrieve
from src.schemas import AgentResponse
from src.tools.web_search import web_search


class SubQueryResult(TypedDict):
    sub_query: str
    documents: list[Document]


class DecomposeState(TypedDict):
    question: str
    route: str
    route_reason: str
    sub_queries: list[str]
    decomposition_reason: str
    sub_results: Annotated[list[SubQueryResult], operator.add]
    answer: str
    sources: list[str]
    steps: Annotated[list[str], operator.add]


class RetrieveSubState(TypedDict):
    """State passed to each parallel retrieve worker via Send."""

    sub_query: str
    question: str


def classify_node(state: DecomposeState) -> dict:
    decision = router_chain.invoke({"question": state["question"]})
    return {
        "route": decision.route.value,
        "route_reason": decision.reason,
        "steps": [f"Router → {decision.route.value}: {decision.reason}"],
    }


def direct_answer_node(state: DecomposeState) -> dict:
    answer = direct_chain.invoke({"question": state["question"]})
    return {"answer": answer, "sources": [], "steps": ["Direct answer (no retrieval)"]}


def decompose_node(state: DecomposeState) -> dict:
    """LangChain decompose_chain splits the question into sub-queries."""
    result = decompose_chain.invoke({"question": state["question"]})
    steps = [f"Decomposer: {len(result.sub_queries)} sub-queries — {result.reasoning}"]
    for i, sq in enumerate(result.sub_queries, 1):
        steps.append(f"  Sub-query {i}: {sq}")
    return {
        "sub_queries": result.sub_queries,
        "decomposition_reason": result.reasoning,
        "steps": steps,
    }


def fan_out_to_retrieve(state: DecomposeState) -> list[Send]:
    """LangGraph Send: dispatch parallel retrieval workers (map step)."""
    return [
        Send("retrieve_sub", {"sub_query": sq, "question": state["question"]})
        for sq in state["sub_queries"]
    ]


def retrieve_sub_node(state: RetrieveSubState) -> dict:
    """Worker: retrieve documents for one sub-query."""
    docs = retrieve(state["sub_query"])
    return {
        "sub_results": [{"sub_query": state["sub_query"], "documents": docs}],
        "steps": [f"Retrieved {len(docs)} chunks for: '{state['sub_query']}'"],
    }


def synthesize_node(state: DecomposeState) -> dict:
    """Reduce step: combine all sub-query contexts and synthesize one answer."""
    context_parts = []
    all_sources: set[str] = set()

    for i, result in enumerate(state["sub_results"], 1):
        sq = result["sub_query"]
        docs = result["documents"]
        for doc in docs:
            all_sources.add(doc.metadata.get("source", "unknown"))
        context_parts.append(f"## Sub-query {i}: {sq}\n{format_docs(docs)}")

    combined_context = "\n\n".join(context_parts)
    answer = synthesis_chain.invoke({"question": state["question"], "context": combined_context})

    return {
        "answer": answer,
        "sources": list(all_sources),
        "steps": [f"Synthesized answer from {len(state['sub_results'])} sub-query retrievals"],
    }


def web_search_node(state: DecomposeState) -> dict:
    context = web_search.invoke(state["question"])
    answer = web_search_chain.invoke({"context": context, "question": state["question"]})
    return {
        "answer": answer,
        "sources": ["web search"],
        "steps": ["Web search + generated answer"],
    }


def route_condition(state: DecomposeState) -> Literal["direct", "decompose", "web_search"]:
    if state["route"] == RouteType.DIRECT.value:
        return "direct"
    if state["route"] == RouteType.WEB_SEARCH.value:
        return "web_search"
    return "decompose"


def build_decompose_graph():
    graph = StateGraph(DecomposeState)

    graph.add_node("classify", classify_node)
    graph.add_node("direct_answer", direct_answer_node)
    graph.add_node("decompose", decompose_node)
    graph.add_node("retrieve_sub", retrieve_sub_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("web_search", web_search_node)

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        route_condition,
        {
            "direct": "direct_answer",
            "decompose": "decompose",
            "web_search": "web_search",
        },
    )
    graph.add_edge("direct_answer", END)
    graph.add_edge("web_search", END)
    graph.add_conditional_edges("decompose", fan_out_to_retrieve, ["retrieve_sub"])
    graph.add_edge("retrieve_sub", "synthesize")
    graph.add_edge("synthesize", END)

    return graph.compile()


_decompose_graph = None


def get_decompose_graph():
    global _decompose_graph
    if _decompose_graph is None:
        _decompose_graph = build_decompose_graph()
    return _decompose_graph


def ask_decompose(question: str) -> AgentResponse:
    """Run the Phase 4 query decomposition agent."""
    graph = get_decompose_graph()
    result = graph.invoke(
        {
            "question": question,
            "route": "",
            "route_reason": "",
            "sub_queries": [],
            "decomposition_reason": "",
            "sub_results": [],
            "answer": "",
            "sources": [],
            "steps": [],
        }
    )
    return AgentResponse(
        answer=result["answer"],
        mode="decompose",
        sources=result.get("sources", []),
        route=result.get("route"),
        route_reason=result.get("route_reason"),
        sub_queries=result.get("sub_queries") or None,
        decomposition_reason=result.get("decomposition_reason") or None,
        steps=result.get("steps", []),
    )
