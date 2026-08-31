"""
Phase 2: LangGraph query router.

Uses LangGraph for orchestration and LangChain inside each node:
  - router_chain     (classify)
  - direct_chain     (direct path)
  - retrieve()       (retrieve path)
  - rag_chain        (generate path)
  - web_search tool  (web path)

Graph flow:
  START → classify → [direct | retrieve | web_search] → END
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from langchain_core.documents import Document
from langgraph.graph import END, START, StateGraph

from src.agents.router import RouteType, router_chain
from src.chains.generation import direct_chain, rag_chain, web_search_chain
from src.retrieval.citations import build_response, docs_to_context, docs_to_sources
from src.retrieval.retriever import EMPTY_RETRIEVAL_MESSAGE, format_docs, retrieve
from src.schemas import AgentResponse, Citation
from src.streaming import run_graph_streaming, stream_text
from src.tools.web_search import web_search


class RouterState(TypedDict):
    question: str
    route: str
    route_reason: str
    documents: list[Document]
    web_context: str
    answer: str
    sources: list[str]
    steps: Annotated[list[str], operator.add]


def classify_node(state: RouterState) -> dict:
    """Node: LangChain router_chain classifies the query."""
    decision = router_chain.invoke({"question": state["question"]})
    return {
        "route": decision.route.value,
        "route_reason": decision.reason,
        "steps": [f"Router → {decision.route.value}: {decision.reason}"],
    }


def direct_answer_node(state: RouterState) -> dict:
    """Node: LangChain direct_chain answers without retrieval."""
    answer = stream_text(direct_chain, {"question": state["question"]})
    return {
        "answer": answer,
        "sources": [],
        "documents": [],
        "steps": ["Direct answer (no retrieval)"],
    }


def retrieve_node(state: RouterState) -> dict:
    """Node: hybrid/MMR/similarity retriever fetches documents."""
    docs = retrieve(state["question"])
    return {
        "documents": docs,
        "sources": docs_to_sources(docs),
        "steps": [f"Retrieved {len(docs)} chunks from knowledge base"],
    }


def generate_node(state: RouterState) -> dict:
    """Node: LangChain rag_chain generates from retrieved context."""
    docs = state.get("documents") or []
    if not docs:
        return {
            "answer": EMPTY_RETRIEVAL_MESSAGE,
            "steps": ["No documents retrieved — skipped generation"],
        }
    context = format_docs(docs)
    answer = stream_text(
        rag_chain, {"context": context, "question": state["question"]}
    )
    return {
        "answer": answer,
        "steps": ["Generated answer from retrieved context"],
    }


def web_search_node(state: RouterState) -> dict:
    """Node: LangChain web_search tool + web_search_chain."""
    context = web_search.invoke(state["question"])
    answer = stream_text(
        web_search_chain, {"context": context, "question": state["question"]}
    )
    return {
        "web_context": context,
        "answer": answer,
        "sources": ["web search"],
        "documents": [],
        "steps": ["Web search + generated answer"],
    }


def route_condition(state: RouterState) -> Literal["direct", "retrieve", "web_search"]:
    """Conditional edge: branch based on router decision."""
    return state["route"]  # type: ignore[return-value]


def build_router_graph():
    """Build and compile the LangGraph StateGraph."""
    graph = StateGraph(RouterState)

    graph.add_node("classify", classify_node)
    graph.add_node("direct_answer", direct_answer_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate_node)
    graph.add_node("web_search", web_search_node)

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        route_condition,
        {
            RouteType.DIRECT.value: "direct_answer",
            RouteType.RETRIEVE.value: "retrieve",
            RouteType.WEB_SEARCH.value: "web_search",
        },
    )
    graph.add_edge("direct_answer", END)
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)
    graph.add_edge("web_search", END)

    return graph.compile()


_router_graph = None


def get_router_graph():
    global _router_graph
    if _router_graph is None:
        _router_graph = build_router_graph()
    return _router_graph


def ask_router(question: str) -> AgentResponse:
    """Run the Phase 2 LangGraph router agent."""
    graph = get_router_graph()
    result = run_graph_streaming(
        graph,
        {
            "question": question,
            "route": "",
            "route_reason": "",
            "documents": [],
            "web_context": "",
            "answer": "",
            "sources": [],
            "steps": [],
        },
    )
    docs = result.get("documents") or []
    citations: list[Citation] = []
    context_docs = docs_to_context(docs)
    if result.get("route") == RouteType.WEB_SEARCH.value and result.get("web_context"):
        context_docs = [result["web_context"]]

    return build_response(
        answer=result["answer"],
        mode="router",
        docs=docs,
        sources=result.get("sources", []),
        context_docs=context_docs,
        citations=citations if not docs else None,
        route=result.get("route"),
        route_reason=result.get("route_reason"),
        steps=result.get("steps", []),
    )
