"""
Phase 5: Multi-Hop Retrieval — LangGraph sequential loop.

Unlike Phase 4 (parallel decomposition), each hop depends on the previous hop's findings.

Flow:
  classify → analyze → retrieve_hop → reflect ──┬─ sufficient → synthesize → END
                                                └─ need more hops → retrieve_hop (loop)
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from langchain_core.documents import Document
from langgraph.graph import END, START, StateGraph

from src.agents.multi_hop import analyze_chain, reflect_chain
from src.agents.router import RouteType, router_chain
from src.chains.generation import direct_chain, synthesis_chain, web_search_chain
from src.config import settings
from src.retrieval.citations import build_response, docs_to_sources
from src.retrieval.retriever import format_docs, retrieve
from src.schemas import AgentResponse
from src.streaming import run_graph_streaming, stream_text
from src.tools.web_search import web_search


class HopResult(TypedDict):
    hop_number: int
    search_query: str
    finding: str
    documents: list[Document]


class MultiHopState(TypedDict):
    question: str
    route: str
    route_reason: str
    skip_router: bool
    needs_multi_hop: bool
    multi_hop_reason: str
    current_hop: int
    search_query: str
    sufficient: bool
    hop_results: list[HopResult]
    answer: str
    sources: list[str]
    steps: Annotated[list[str], operator.add]


def classify_node(state: MultiHopState) -> dict:
    if state.get("skip_router") and state.get("route"):
        return {
            "steps": [f"Router skipped (parent set route={state['route']})"],
        }
    decision = router_chain.invoke({"question": state["question"]})
    return {
        "route": decision.route.value,
        "route_reason": decision.reason,
        "steps": [f"Router → {decision.route.value}: {decision.reason}"],
    }


def direct_answer_node(state: MultiHopState) -> dict:
    answer = stream_text(direct_chain, {"question": state["question"]})
    return {"answer": answer, "sources": [], "steps": ["Direct answer (no retrieval)"]}


def web_search_node(state: MultiHopState) -> dict:
    context = web_search.invoke(state["question"])
    answer = stream_text(
        web_search_chain, {"context": context, "question": state["question"]}
    )
    return {
        "answer": answer,
        "sources": ["web search"],
        "steps": ["Web search + generated answer"],
    }


def analyze_node(state: MultiHopState) -> dict:
    """LangChain analyze_chain plans the first hop."""
    analysis = analyze_chain.invoke({"question": state["question"]})
    mode = "multi-hop" if analysis.needs_multi_hop else "single-hop"
    return {
        "needs_multi_hop": analysis.needs_multi_hop,
        "multi_hop_reason": analysis.reasoning,
        "search_query": analysis.first_search_query,
        "current_hop": 0,
        "sufficient": False,
        "steps": [f"Multi-hop analyzer ({mode}): {analysis.reasoning}"],
    }


def retrieve_hop_node(state: MultiHopState) -> dict:
    """Sequential hop: retrieve using the current search query."""
    hop_number = state["current_hop"] + 1
    docs = retrieve(state["search_query"])
    new_hop: HopResult = {
        "hop_number": hop_number,
        "search_query": state["search_query"],
        "finding": "",
        "documents": docs,
    }
    return {
        "current_hop": hop_number,
        "hop_results": state["hop_results"] + [new_hop],
        "steps": [f"Hop {hop_number}: retrieved {len(docs)} chunks for '{state['search_query']}'"],
    }


def _build_hop_history(hop_results: list[HopResult]) -> str:
    lines = []
    for hop in hop_results[:-1]:
        finding = hop.get("finding") or "No finding recorded"
        lines.append(f"Hop {hop['hop_number']} ('{hop['search_query']}'): {finding}")
    return "\n".join(lines) if lines else "None yet"


def reflect_node(state: MultiHopState) -> dict:
    """LangChain reflect_chain decides: answer now or continue to next hop."""
    current = state["hop_results"][-1]
    context = format_docs(current["documents"])
    hop_history = _build_hop_history(state["hop_results"])

    reflection = reflect_chain.invoke(
        {
            "question": state["question"],
            "hop_number": current["hop_number"],
            "search_query": current["search_query"],
            "context": context,
            "hop_history": hop_history,
        }
    )

    # Record finding on the current hop
    updated_hops = state["hop_results"][:-1] + [{**current, "finding": reflection.intermediate_finding}]

    steps = [f"Hop {current['hop_number']} reflection: {reflection.intermediate_finding}"]
    if reflection.sufficient:
        steps.append("Sufficient context — ready to synthesize")
    elif reflection.next_search_query:
        steps.append(f"Next hop query: '{reflection.next_search_query}'")

    result: dict = {
        "sufficient": reflection.sufficient,
        "hop_results": updated_hops,
        "steps": steps,
    }
    if not reflection.sufficient and reflection.next_search_query:
        result["search_query"] = reflection.next_search_query

    return result


def synthesize_node(state: MultiHopState) -> dict:
    """Combine all hop contexts into a final answer."""
    context_parts = []
    all_docs: list[Document] = []

    for hop in state["hop_results"]:
        all_docs.extend(hop["documents"])
        context_parts.append(
            f"## Hop {hop['hop_number']}: {hop['search_query']}\n"
            f"Finding: {hop['finding']}\n"
            f"{format_docs(hop['documents'])}"
        )

    combined = "\n\n".join(context_parts)
    answer = stream_text(
        synthesis_chain, {"question": state["question"], "context": combined}
    )

    return {
        "answer": answer,
        "sources": docs_to_sources(all_docs),
        "steps": [f"Synthesized answer from {len(state['hop_results'])} hop(s)"],
    }


def route_condition(state: MultiHopState) -> Literal["direct", "analyze", "web_search"]:
    if state["route"] == RouteType.DIRECT.value:
        return "direct"
    if state["route"] == RouteType.WEB_SEARCH.value:
        return "web_search"
    return "analyze"


def reflect_condition(state: MultiHopState) -> Literal["synthesize", "retrieve_hop"]:
    if state["sufficient"]:
        return "synthesize"
    # Single-hop questions: one retrieval is enough
    if not state["needs_multi_hop"] and state["current_hop"] >= 1:
        return "synthesize"
    if state["current_hop"] >= settings.max_multi_hop_steps:
        return "synthesize"
    return "retrieve_hop"


def build_multi_hop_graph():
    graph = StateGraph(MultiHopState)

    graph.add_node("classify", classify_node)
    graph.add_node("direct_answer", direct_answer_node)
    graph.add_node("web_search", web_search_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("retrieve_hop", retrieve_hop_node)
    graph.add_node("reflect", reflect_node)
    graph.add_node("synthesize", synthesize_node)

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        route_condition,
        {
            "direct": "direct_answer",
            "analyze": "analyze",
            "web_search": "web_search",
        },
    )
    graph.add_edge("direct_answer", END)
    graph.add_edge("web_search", END)
    graph.add_edge("analyze", "retrieve_hop")
    graph.add_edge("retrieve_hop", "reflect")
    graph.add_conditional_edges(
        "reflect",
        reflect_condition,
        {
            "synthesize": "synthesize",
            "retrieve_hop": "retrieve_hop",
        },
    )
    graph.add_edge("synthesize", END)

    return graph.compile()


_multi_hop_graph = None


def get_multi_hop_graph():
    global _multi_hop_graph
    if _multi_hop_graph is None:
        _multi_hop_graph = build_multi_hop_graph()
    return _multi_hop_graph


def ask_multi_hop(question: str) -> AgentResponse:
    """Run the Phase 5 multi-hop retrieval agent."""
    graph = get_multi_hop_graph()
    result = run_graph_streaming(
        graph,
        {
            "question": question,
            "route": "",
            "route_reason": "",
            "skip_router": False,
            "needs_multi_hop": False,
            "multi_hop_reason": "",
            "current_hop": 0,
            "search_query": "",
            "sufficient": False,
            "hop_results": [],
            "answer": "",
            "sources": [],
            "steps": [],
        },
    )
    hop_queries = [h["search_query"] for h in result.get("hop_results", [])]
    docs = [doc for hop in result.get("hop_results", []) for doc in hop["documents"]]
    return build_response(
        answer=result["answer"],
        mode="multi_hop",
        docs=docs,
        sources=result.get("sources", []),
        route=result.get("route"),
        route_reason=result.get("route_reason"),
        sub_queries=hop_queries or None,
        decomposition_reason=result.get("multi_hop_reason") or None,
        steps=result.get("steps", []),
    )
