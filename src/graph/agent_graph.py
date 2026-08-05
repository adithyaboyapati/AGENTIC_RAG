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
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from langchain_core.documents import Document
from langgraph.graph import END, START, StateGraph

from src.agents.grader import grade_documents, summarize_grades
from src.agents.orchestrator import choose_strategy
from src.agents.query_rewriter import rewrite_query
from src.agents.router import RouteType, router_chain
from src.chains.generation import direct_chain, rag_chain, web_search_chain
from src.config import settings
from src.retrieval.retriever import format_docs, retrieve
from src.schemas import AgentResponse
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


def classify_node(state: AgentState) -> dict:
    """Route: direct, retrieve, or web."""
    decision = router_chain.invoke({"question": state["question"]})
    return {
        "route": decision.route.value,
        "route_reason": decision.reason,
        "steps": [f"Router → {decision.route.value}: {decision.reason}"],
    }


def strategy_node(state: AgentState) -> dict:
    """Choose best retrieval strategy: decompose, multi_hop, tools, or simple."""
    choice = choose_strategy(state["question"])
    return {
        "strategy": choice.strategy,
        "strategy_reason": choice.reasoning,
        "steps": [f"Strategy: {choice.strategy} — {choice.reasoning}"],
    }


def direct_answer_node(state: AgentState) -> dict:
    answer = direct_chain.invoke({"question": state["question"]})
    return {"answer": answer, "sources": [], "steps": ["Direct answer (no retrieval)"]}


def web_search_node(state: AgentState) -> dict:
    context = web_search.invoke(state["question"])
    answer = web_search_chain.invoke({"context": context, "question": state["question"]})
    return {
        "answer": answer,
        "sources": ["web search"],
        "steps": ["Web search + generated answer"],
    }


def decompose_node(state: AgentState) -> dict:
    """Decompose into parallel sub-queries."""
    from src.graph.decompose_graph import get_decompose_graph

    graph = get_decompose_graph()
    result = graph.invoke(
        {
            "question": state["question"],
            "route": state["route"],
            "route_reason": state["route_reason"],
            "sub_queries": [],
            "decomposition_reason": "",
            "sub_results": [],
            "answer": "",
            "sources": [],
            "steps": [],
        }
    )
    return {
        "documents": [doc for sub in result.get("sub_results", []) for doc in sub["documents"]],
        "filtered_documents": [doc for sub in result.get("sub_results", []) for doc in sub["documents"]],
        "answer": result["answer"],
        "sources": result.get("sources", []),
        "steps": [f"Decomposed + synthesized from {len(result.get('sub_results', []))} sub-queries"],
    }


def multi_hop_node(state: AgentState) -> dict:
    """Sequential multi-hop retrieval."""
    from src.graph.multi_hop_graph import get_multi_hop_graph

    graph = get_multi_hop_graph()
    result = graph.invoke(
        {
            "question": state["question"],
            "route": state["route"],
            "route_reason": state["route_reason"],
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
    return {
        "documents": [doc for hop in result.get("hop_results", []) for doc in hop["documents"]],
        "filtered_documents": [doc for hop in result.get("hop_results", []) for doc in hop["documents"]],
        "answer": result["answer"],
        "sources": result.get("sources", []),
        "steps": [f"Multi-hop: {len(result.get('hop_results', []))} sequential retrievals"],
    }


def tools_node(state: AgentState) -> dict:
    """Tool-calling agent."""
    from src.graph.tools_graph import get_tools_graph

    graph = get_tools_graph()
    result = graph.invoke(
        {
            "question": state["question"],
            "route": state["route"],
            "route_reason": state["route_reason"],
            "messages": [],
            "answer": "",
            "sources": [],
            "steps": [],
        }
    )
    return {
        "answer": result["answer"],
        "sources": result.get("sources", []),
        "steps": [f"Tool-augmented: {len(result.get('steps', []))} tool calls"],
    }


def simple_retrieve_node(state: AgentState) -> dict:
    """Simple single-pass retrieval."""
    docs = retrieve(state["question"])
    sources = list({doc.metadata.get("source", "unknown") for doc in docs})
    return {
        "documents": docs,
        "sources": sources,
        "steps": [f"Simple retrieval: fetched {len(docs)} chunks"],
    }


def grade_node(state: AgentState) -> dict:
    """Grade documents (CRAG safety net)."""
    if not state["documents"]:
        return {
            "filtered_documents": [],
            "grade_summary": "No documents to grade",
            "steps": ["Grader: No documents"],
        }
    filtered, result = grade_documents(state["question"], state["documents"])
    summary = summarize_grades(result)
    return {
        "filtered_documents": filtered,
        "grade_summary": summary,
        "steps": [f"Grader: {summary}"],
    }


def generate_node(state: AgentState) -> dict:
    """Generate from graded documents."""
    if state["filtered_documents"]:
        context = format_docs(state["filtered_documents"])
        answer = rag_chain.invoke({"context": context, "question": state["question"]})
    else:
        answer = state.get("answer") or "Unable to generate a comprehensive answer from available context."
    return {
        "answer": answer,
        "steps": [f"Generated from {len(state['filtered_documents'])} relevant chunks"],
    }


def rewrite_node(state: AgentState) -> dict:
    """Rewrite query and retry."""
    rewritten = rewrite_query(state["question"], state["question"])
    new_docs = retrieve(rewritten.query)
    sources = list({doc.metadata.get("source", "unknown") for doc in new_docs})
    return {
        "documents": new_docs,
        "sources": sources,
        "retry_count": state["retry_count"] + 1,
        "steps": [f"Query rewrite (attempt {state['retry_count'] + 2}): {rewritten.reason}"],
    }


def fallback_node(state: AgentState) -> dict:
    """Web fallback when retrieval fails."""
    context = web_search.invoke(state["question"])
    answer = web_search_chain.invoke({"context": context, "question": state["question"]})
    return {
        "answer": answer,
        "sources": ["web search (fallback)"],
        "steps": ["Fallback: web search (docs insufficient)"],
    }


def route_condition(state: AgentState) -> Literal["direct", "retrieve", "web_search"]:
    if state["route"] == RouteType.DIRECT.value:
        return "direct"
    if state["route"] == RouteType.WEB_SEARCH.value:
        return "web_search"
    return "retrieve"


def strategy_condition(state: AgentState) -> Literal["decompose", "multi_hop", "tools", "simple"]:
    return state["strategy"]


def grade_condition(state: AgentState) -> Literal["generate", "rewrite", "fallback"]:
    if state["filtered_documents"]:
        return "generate"
    if state["retry_count"] < settings.max_retrieval_retries:
        return "rewrite"
    return "fallback"


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

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        route_condition,
        {
            "direct": "direct_answer",
            "retrieve": "strategy",
            "web_search": "web_search",
        },
    )
    graph.add_edge("direct_answer", END)
    graph.add_edge("web_search", END)
    graph.add_conditional_edges(
        "strategy",
        strategy_condition,
        {
            "decompose": "decompose",
            "multi_hop": "multi_hop",
            "tools": "tools",
            "simple": "simple_retrieve",
        },
    )
    graph.add_edge("decompose", END)
    graph.add_edge("multi_hop", END)
    graph.add_edge("tools", END)
    graph.add_edge("simple_retrieve", "grade")
    graph.add_conditional_edges(
        "grade",
        grade_condition,
        {
            "generate": "generate",
            "rewrite": "rewrite",
            "fallback": "fallback",
        },
    )
    graph.add_edge("generate", END)
    graph.add_edge("rewrite", "grade")
    graph.add_edge("fallback", END)

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
    result = graph.invoke(
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
        }
    )
    return AgentResponse(
        answer=result["answer"],
        mode="agentic",
        sources=result.get("sources", []),
        route=result.get("route"),
        route_reason=result.get("route_reason"),
        decomposition_reason=result.get("strategy_reason"),
        grade_summary=result.get("grade_summary"),
        steps=result.get("steps", []),
    )
