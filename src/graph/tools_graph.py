"""
Phase 6: Tool-Augmented Agent — LangGraph agent with function calling.

Flow:
  classify → route → [direct | web | tools_agent | tooling_loop]
  
The tools_agent uses LangChain's tool calling:
  LLM picks tool → call tool → observe result → repeat until done
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from src.agents.router import RouteType, router_chain
from src.chains.generation import direct_chain, web_search_chain
from src.schemas import AgentResponse
from src.tools.all_tools import TOOL_MAP, TOOLS
from src.tools.web_search import web_search


class ToolsState(TypedDict):
    question: str
    route: str
    route_reason: str
    messages: Annotated[list[BaseMessage], operator.add]
    answer: str
    sources: list[str]
    steps: Annotated[list[str], operator.add]


def classify_node(state: ToolsState) -> dict:
    decision = router_chain.invoke({"question": state["question"]})
    return {
        "route": decision.route.value,
        "route_reason": decision.reason,
        "messages": [HumanMessage(content=state["question"])],
        "steps": [f"Router → {decision.route.value}: {decision.reason}"],
    }


def direct_answer_node(state: ToolsState) -> dict:
    answer = direct_chain.invoke({"question": state["question"]})
    return {
        "answer": answer,
        "sources": [],
        "steps": ["Direct answer (no tools)"],
    }


def web_search_node(state: ToolsState) -> dict:
    context = web_search.invoke(state["question"])
    answer = web_search_chain.invoke({"context": context, "question": state["question"]})
    return {
        "answer": answer,
        "sources": ["web search"],
        "steps": ["Web search + generated answer"],
    }


def tools_agent_node(state: ToolsState) -> dict:
    """LLM with tool calling: picks tools, executes them, repeats until done."""
    from src.llm import get_llm

    llm = get_llm().bind_tools(TOOLS)

    messages = state["messages"]
    steps = state.get("steps", [])

    max_iterations = 10
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        response = llm.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            break

        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_input = tool_call["args"]
            steps.append(f"Tool call: {tool_name}({', '.join(f'{k}={repr(v)[:50]}' for k, v in tool_input.items())})")

            tool = TOOL_MAP.get(tool_name)
            if tool:
                result = tool.invoke(tool_input)
            else:
                result = f"Tool {tool_name} not found"

            messages.append(ToolMessage(content=result, tool_call_id=tool_call["id"]))

    final_answer = response.content if hasattr(response, "content") else str(response)

    return {
        "answer": final_answer,
        "messages": messages,
        "sources": ["tools"],
        "steps": steps,
    }


def route_condition(state: ToolsState) -> Literal["direct", "tools_agent", "web_search"]:
    if state["route"] == RouteType.DIRECT.value:
        return "direct"
    if state["route"] == RouteType.WEB_SEARCH.value:
        return "web_search"
    return "tools_agent"


def build_tools_graph():
    graph = StateGraph(ToolsState)

    graph.add_node("classify", classify_node)
    graph.add_node("direct_answer", direct_answer_node)
    graph.add_node("web_search", web_search_node)
    graph.add_node("tools_agent", tools_agent_node)

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        route_condition,
        {
            "direct": "direct_answer",
            "tools_agent": "tools_agent",
            "web_search": "web_search",
        },
    )
    graph.add_edge("direct_answer", END)
    graph.add_edge("web_search", END)
    graph.add_edge("tools_agent", END)

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
    result = graph.invoke(
        {
            "question": question,
            "route": "",
            "route_reason": "",
            "messages": [],
            "answer": "",
            "sources": [],
            "steps": [],
        }
    )
    return AgentResponse(
        answer=result["answer"],
        mode="tools",
        sources=result.get("sources", []),
        route=result.get("route"),
        route_reason=result.get("route_reason"),
        steps=result.get("steps", []),
    )
