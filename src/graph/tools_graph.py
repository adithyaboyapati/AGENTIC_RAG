"""
Phase 6: Tool-Augmented Agent — LangGraph agent with function calling.

Flow:
  classify → route → [direct | web | tools_agent]

The tools_agent uses LangChain's tool calling:
  LLM picks tool → call tool → gate result → observe → repeat until done
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from src.agents.router import RouteType, router_chain
from src.chains.generation import direct_chain, web_search_chain
from src.resilience.node_gate import (
    MAX_TOOL_FAILURES,
    PREFIX_TOOL_EMPTY,
    abort_user_message,
    check_answer,
    check_route,
    check_tool_result,
    check_web_context,
    quarantine_tool_message,
)
from src.retrieval.citations import build_response, docs_to_sources
from src.retrieval.retriever import format_docs
from src.schemas import AgentResponse
from src.sources.federation import RETRIEVAL_TOOL_NAMES, TOOL_EMPTY_DETAIL, documents_for_tool
from src.streaming import run_graph_streaming, stream_llm_message, stream_text
from src.tools.all_tools import TOOL_MAP, TOOLS
from src.tools.web_search import web_search


class ToolsState(TypedDict):
    question: str
    route: str
    route_reason: str
    skip_router: bool
    messages: Annotated[list[BaseMessage], operator.add]
    documents: list[Document]
    answer: str
    sources: list[str]
    steps: Annotated[list[str], operator.add]
    abort: bool
    abort_reason: str


def classify_node(state: ToolsState) -> dict:
    if state.get("skip_router") and state.get("route"):
        gate = check_route(state["route"])
        if not gate.ok:
            return {
                "abort": True,
                "abort_reason": gate.message,
                "messages": [HumanMessage(content=state["question"])],
                "steps": [f"Node gate abort [{gate.code}]: {gate.message}"],
            }
        return {
            "messages": [HumanMessage(content=state["question"])],
            "steps": [f"Router skipped (parent set route={state['route']})"],
        }
    try:
        decision = router_chain.invoke({"question": state["question"]})
        route = decision.route.value
        reason = decision.reason
    except Exception as exc:
        return {
            "abort": True,
            "abort_reason": f"Router failed: {type(exc).__name__}",
            "messages": [HumanMessage(content=state["question"])],
            "steps": [f"Node gate abort [router_exception]: {type(exc).__name__}"],
        }

    gate = check_route(route)
    if not gate.ok:
        return {
            "abort": True,
            "abort_reason": gate.message,
            "route": route,
            "route_reason": reason,
            "messages": [HumanMessage(content=state["question"])],
            "steps": [f"Node gate abort [{gate.code}]: {gate.message}"],
        }

    return {
        "route": route,
        "route_reason": reason,
        "messages": [HumanMessage(content=state["question"])],
        "steps": [f"Router → {route}: {reason}"],
    }


def direct_answer_node(state: ToolsState) -> dict:
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
        "steps": ["Direct answer (no tools)"],
    }


def web_search_node(state: ToolsState) -> dict:
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


def tools_agent_node(state: ToolsState) -> dict:
    """LLM with tool calling: picks tools, gates results, repeats until done."""
    if state.get("abort"):
        return {}

    from src.llm import get_llm

    llm = get_llm().bind_tools(TOOLS)

    messages = list(state["messages"])
    steps = list(state.get("steps", []))
    collected_docs: list[Document] = []
    used_web = False
    used_calc = False
    tool_failures = 0

    max_iterations = 10
    iteration = 0
    response = None

    while iteration < max_iterations:
        iteration += 1
        response = stream_llm_message(llm, messages)
        messages.append(response)

        if not response.tool_calls:
            break

        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_input = tool_call["args"]
            steps.append(
                f"Tool call: {tool_name}("
                f"{', '.join(f'{k}={repr(v)[:50]}' for k, v in tool_input.items())})"
            )

            docs_this_call: list[Document] = []
            if tool_name in RETRIEVAL_TOOL_NAMES:
                query = str(tool_input.get("query", state["question"]))
                docs_this_call = documents_for_tool(tool_name, query)
                result = (
                    format_docs(docs_this_call)
                    if docs_this_call
                    else f"{PREFIX_TOOL_EMPTY} {TOOL_EMPTY_DETAIL.get(tool_name, 'No results.')}"
                )
            elif tool_name in TOOL_MAP:
                tool = TOOL_MAP[tool_name]
                result = tool.invoke(tool_input)
            else:
                result = f"Tool {tool_name} not found"

            gate = check_tool_result(tool_name, str(result))
            if gate.severity == "quarantine":
                tool_failures += 1
                try:
                    from src.api.metrics import record_node_gate

                    record_node_gate("quarantine")
                except Exception:
                    pass
                steps.append(
                    f"Node gate quarantine [{gate.code}]: {tool_name} — {gate.message}"
                )
                messages.append(
                    ToolMessage(
                        content=quarantine_tool_message(gate, tool_name),
                        tool_call_id=tool_call["id"],
                    )
                )
                if tool_failures >= MAX_TOOL_FAILURES:
                    return {
                        "abort": True,
                        "abort_reason": (
                            f"Too many tool failures ({tool_failures}); "
                            "stopping to avoid contaminating the answer"
                        ),
                        "answer": "",
                        "messages": messages,
                        "documents": collected_docs,
                        "sources": docs_to_sources(collected_docs),
                        "steps": steps
                        + [
                            f"Node gate abort [tool_failure_budget]: "
                            f"{tool_failures} quarantined tool results"
                        ],
                    }
                continue

            # Healthy result — only then count web/calc / collect docs
            if tool_name in RETRIEVAL_TOOL_NAMES:
                collected_docs.extend(docs_this_call)
            elif tool_name == "web_search":
                used_web = True
            elif tool_name == "calculator":
                used_calc = True

            messages.append(ToolMessage(content=str(result), tool_call_id=tool_call["id"]))

    final_answer = response.content if response is not None and hasattr(response, "content") else ""
    ans_gate = check_answer(str(final_answer or ""), required=True)
    if not ans_gate.ok:
        return {
            "abort": True,
            "abort_reason": ans_gate.message,
            "answer": "",
            "messages": messages,
            "documents": collected_docs,
            "sources": docs_to_sources(collected_docs),
            "steps": steps + [f"Node gate abort [{ans_gate.code}]: {ans_gate.message}"],
        }

    sources = docs_to_sources(collected_docs)
    if used_web:
        sources = list(dict.fromkeys([*sources, "web search"]))
    if used_calc and not sources:
        sources = ["calculator"]
    if not sources:
        sources = ["tools"]

    return {
        "answer": final_answer,
        "messages": messages,
        "documents": collected_docs,
        "sources": sources,
        "steps": steps,
    }


def abort_node(state: ToolsState) -> dict:
    reason = state.get("abort_reason") or "a required step failed"
    return {
        "answer": abort_user_message(reason),
        "sources": [],
        "documents": [],
        "steps": [f"Aborted: {reason}"],
    }


def route_condition(state: ToolsState) -> Literal["direct", "tools_agent", "web_search", "abort"]:
    if state.get("abort"):
        return "abort"
    if state["route"] == RouteType.DIRECT.value:
        return "direct"
    if state["route"] == RouteType.WEB_SEARCH.value:
        return "web_search"
    return "tools_agent"


def after_node_condition(state: ToolsState) -> Literal["abort", "end"]:
    return "abort" if state.get("abort") else "end"


def build_tools_graph():
    graph = StateGraph(ToolsState)

    graph.add_node("classify", classify_node)
    graph.add_node("direct_answer", direct_answer_node)
    graph.add_node("web_search", web_search_node)
    graph.add_node("tools_agent", tools_agent_node)
    graph.add_node("abort", abort_node)

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        route_condition,
        {
            "direct": "direct_answer",
            "tools_agent": "tools_agent",
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
        "tools_agent",
        after_node_condition,
        {"abort": "abort", "end": END},
    )
    graph.add_edge("abort", END)

    return graph.compile()


_tools_graph = None


def get_tools_graph():
    global _tools_graph
    if _tools_graph is None:
        _tools_graph = build_tools_graph()
    return _tools_graph


def ask_tools(question: str) -> AgentResponse:
    """Run the Phase 6 tool-augmented agent."""
    graph = get_tools_graph()
    result = run_graph_streaming(
        graph,
        {
            "question": question,
            "route": "",
            "route_reason": "",
            "skip_router": False,
            "messages": [],
            "documents": [],
            "answer": "",
            "sources": [],
            "steps": [],
            "abort": False,
            "abort_reason": "",
        },
    )
    docs = result.get("documents") or []
    error_code = "node_gate_abort" if result.get("abort") else None
    # abort_node already set a safe answer; if abort without going through abort_node
    answer = result.get("answer") or ""
    if result.get("abort") and not answer:
        answer = abort_user_message(result.get("abort_reason"))
    return build_response(
        answer=answer,
        mode="tools",
        docs=[] if error_code else docs,
        sources=[] if error_code else result.get("sources", []),
        route=result.get("route"),
        route_reason=result.get("route_reason"),
        steps=result.get("steps", []),
        error_code=error_code,
    )
