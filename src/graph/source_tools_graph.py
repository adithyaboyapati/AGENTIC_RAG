"""LLM-selected source tools: PDF, SQLite catalog, ops API, lab MCP, calculator.

This is a distinct public mode from canonical federation. The model chooses
which source(s) to query; PDF retrieval does not auto-merge extra sources.
"""

from __future__ import annotations

import json
import logging
import operator
from typing import Annotated, Any, TypedDict

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from src.agents.grader import grade_documents, summarize_grades
from src.config import settings
from src.llm import get_llm
from src.resilience.node_gate import PREFIX_TOOL_EMPTY, PREFIX_TOOL_ERROR, check_tool_result
from src.observability import graph_tracing_config, optional_traceable
from src.retrieval.citations import build_response
from src.retrieval.context import current_rbac
from src.retrieval.retriever import format_docs, retrieve
from src.schemas import AgentResponse, RBACContext
from src.streaming import run_graph_streaming, stream_llm_message

logger = logging.getLogger(__name__)

SOURCE_TOOLS_MODE = "source_tools"

SOURCE_TOOLS_PROMPT = """You are a research assistant with source tools. Choose tools to gather evidence, then answer.

Tools:
- retrieve_pdf — indexed PDF corpus (RAG / Self-RAG / CRAG concepts).
- query_database — SQLite research catalog (papers, authors, citation counts, benchmarks).
- query_api — ops catalog (who owns a service, incidents, SLAs, glossary).
- query_mcp — lab notes (experiment ids like exp-42, ablations, runbooks).
- calculator — arithmetic only. Always use this for math; do not compute yourself.

Rules:
- Pick the smallest set of tools that can answer the question. You may call several.
- After you have enough evidence, answer in prose. Cite tool snippets with [1], [2].
- If a tool returns no relevant evidence after grading, try a different source or a sharper query.
- Never invent catalog owners, experiment results, or citation counts.
"""


@tool
def retrieve_pdf(query: str) -> str:
    """Search the indexed PDF knowledge base only (no database / API / MCP merge)."""
    docs = retrieve(query, include_extra=False, rbac_context=current_rbac())
    if not docs:
        return f"{PREFIX_TOOL_EMPTY} No PDF chunks found."
    return format_docs(docs, query=query)


@tool
def query_database(query: str) -> str:
    """Look up the SQLite research catalog (papers, benchmarks, deployments)."""
    from src.sources.database import search_database
    from src.sources.federation import filter_documents_rbac

    docs = filter_documents_rbac(search_database(query), current_rbac())
    if not docs:
        return f"{PREFIX_TOOL_EMPTY} No database records found."
    return format_docs(docs)


@tool
def query_api(query: str) -> str:
    """Search the ops catalog API (owners, incidents, SLAs, glossary)."""
    from src.sources.federation import filter_documents_rbac
    from src.sources.sample_api import search_api

    docs = filter_documents_rbac(search_api(query), current_rbac())
    if not docs:
        return f"{PREFIX_TOOL_EMPTY} No catalog API results found."
    return format_docs(docs)


@tool
def query_mcp(query: str) -> str:
    """Query lab-notes MCP (experiments, ablations, runbooks)."""
    from src.sources.federation import filter_documents_rbac
    from src.sources.mcp_server import search_mcp

    docs = filter_documents_rbac(search_mcp(query), current_rbac())
    if not docs:
        return f"{PREFIX_TOOL_EMPTY} No MCP lab knowledge found."
    return format_docs(docs)


@tool
def calculator(expression: str) -> str:
    """Evaluate a mathematical expression with operator precedence."""
    from src.tools.all_tools import safe_calculate

    try:
        return str(safe_calculate(expression))
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as exc:
        return f"{PREFIX_TOOL_ERROR} Error evaluating '{expression}': {exc}"


SOURCE_SELECT_TOOLS = [retrieve_pdf, query_database, query_api, query_mcp, calculator]
SOURCE_TOOL_MAP = {t.name: t for t in SOURCE_SELECT_TOOLS}


class SourceToolsState(TypedDict, total=False):
    question: str
    messages: Annotated[list, add_messages]
    steps: Annotated[list[str], operator.add]
    documents: Annotated[list[Document], operator.add]
    tool_calls_log: Annotated[list[dict[str, Any]], operator.add]
    grade_summaries: Annotated[list[str], operator.add]
    rounds: int
    answer: str


def _brief_args(args: dict[str, Any]) -> str:
    if not args:
        return ""
    if "query" in args:
        return str(args["query"])[:80]
    if "expression" in args:
        return str(args["expression"])[:80]
    return json.dumps(args, default=str)[:80]


def _source_docs_trace_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    args = inputs.get("args") or {}
    return {
        "tool": inputs.get("name"),
        "query": args.get("query") if isinstance(args, dict) else None,
    }


def _source_docs_trace_outputs(docs: list[Document]) -> dict[str, Any]:
    if not isinstance(docs, list):
        return {"count": 0}
    return {
        "count": len(docs),
        "chunk_ids": [(d.metadata or {}).get("chunk_id") for d in docs[:20]],
    }


@optional_traceable(
    "source_tool_retrieve",
    run_type="retriever",
    process_inputs=_source_docs_trace_inputs,
    process_outputs=_source_docs_trace_outputs,
)
def _docs_for_call(name: str, args: dict[str, Any], rbac: RBACContext) -> list[Document]:
    query = str(args.get("query") or "").strip()
    if not query:
        return []
    if name == "retrieve_pdf":
        return retrieve(query, include_extra=False, rbac_context=rbac)
    from src.sources.federation import filter_documents_rbac

    if name == "query_database":
        from src.sources.database import search_database

        return filter_documents_rbac(search_database(query), rbac)
    if name == "query_api":
        from src.sources.sample_api import search_api

        return filter_documents_rbac(search_api(query), rbac)
    if name == "query_mcp":
        from src.sources.mcp_server import search_mcp

        return filter_documents_rbac(search_mcp(query), rbac)
    return []


def _grade_source_docs(question: str, documents: list[Document]) -> tuple[list[Document], str]:
    """CRAG-grade source-backed tool hits; fail open if the grader errors."""
    if not documents:
        return [], "No documents to grade"
    try:
        kept, grading = grade_documents(question, documents)
    except Exception:
        logger.warning("Source-tools grader failed — keeping retrieved docs", exc_info=True)
        return documents, "Grader failed — kept retrieved chunks"
    return kept, summarize_grades(grading)


def agent_node(state: SourceToolsState) -> dict[str, Any]:
    rounds = int(state.get("rounds") or 0) + 1
    bound = get_llm().bind_tools(SOURCE_SELECT_TOOLS)
    response = stream_llm_message(bound, state["messages"])
    return {"messages": [response], "rounds": rounds, "steps": [f"Tool agent round {rounds}: choosing sources"]}


def tools_node(state: SourceToolsState) -> dict[str, Any]:
    last = state["messages"][-1]
    calls = getattr(last, "tool_calls", None) or []
    rbac = current_rbac()
    messages: list[ToolMessage] = []
    docs: list[Document] = []
    log: list[dict[str, Any]] = []
    steps: list[str] = []
    grade_summaries: list[str] = []

    for call in calls:
        name = str(call.get("name") or "")
        args = dict(call.get("args") or {})
        call_id = str(call.get("id") or name)
        brief = _brief_args(args)
        tool = SOURCE_TOOL_MAP.get(name)
        fetched: list[Document] = []
        if tool is None:
            output = f"{PREFIX_TOOL_ERROR} Unknown tool '{name}'."
        elif name == "calculator":
            try:
                output = str(tool.invoke(args))
            except Exception as exc:
                logger.warning("Source tool %s failed", name, exc_info=True)
                output = f"{PREFIX_TOOL_ERROR} {name} failed: {type(exc).__name__}"
        else:
            try:
                fetched = _docs_for_call(name, args, rbac)
                if not fetched:
                    output = f"{PREFIX_TOOL_EMPTY} No {name} results found."
                else:
                    kept, grade_summary = _grade_source_docs(str(state.get("question") or ""), fetched)
                    fetched = kept
                    steps.append(f"Graded {name}: {grade_summary}")
                    grade_summaries.append(grade_summary)
                    output = (
                        format_docs(fetched, query=str(args.get("query") or "") or None)
                        if fetched
                        else f"{PREFIX_TOOL_EMPTY} No relevant evidence after grading."
                    )
            except Exception as exc:
                logger.warning("Source tool %s failed", name, exc_info=True)
                output = f"{PREFIX_TOOL_ERROR} {name} failed: {type(exc).__name__}"

        gate = check_tool_result(name, output)
        if gate.ok and fetched:
            docs.extend(fetched)

        messages.append(ToolMessage(content=output, tool_call_id=call_id))
        log.append({"tool": name, "args": brief, "ok": gate.ok, "code": gate.code})
        status = "ok" if gate.ok else gate.code
        steps.append(f"Tool → {name}({brief}) [{status}]")

    return {
        "messages": messages,
        "documents": docs,
        "tool_calls_log": log,
        "steps": steps,
        "grade_summaries": grade_summaries,
    }


def route_after_agent(state: SourceToolsState) -> str:
    last = state["messages"][-1]
    has_tools = bool(getattr(last, "tool_calls", None))
    if has_tools and int(state.get("rounds") or 0) <= max(1, settings.source_tools_max_rounds):
        return "tools"
    return "finalize"


def finalize_node(state: SourceToolsState) -> dict[str, Any]:
    last = next(
        (m for m in reversed(state.get("messages") or []) if isinstance(m, AIMessage)),
        None,
    )
    answer = ""
    if last is not None and not getattr(last, "tool_calls", None):
        answer = (last.content or "") if isinstance(last.content, str) else str(last.content or "")
    if not answer.strip():
        answer = "I couldn't gather enough evidence from the selected sources to answer."
    return {"answer": answer, "steps": ["Tool agent finished"]}


def build_source_tools_graph():
    graph = StateGraph(SourceToolsState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("finalize", finalize_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        route_after_agent,
        {"tools": "tools", "finalize": "finalize"},
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("finalize", END)
    return graph.compile(name="source_tools")


_source_tools_graph = None


def get_source_tools_graph():
    global _source_tools_graph
    if _source_tools_graph is None:
        _source_tools_graph = build_source_tools_graph()
    return _source_tools_graph


def reset_source_tools_graph() -> None:
    global _source_tools_graph
    _source_tools_graph = None


def ask_source_tools(question: str, *, rbac_context: RBACContext | None = None) -> AgentResponse:
    """Run the source-tools ReAct loop and return an API AgentResponse."""
    graph = get_source_tools_graph()
    initial: SourceToolsState = {
        "question": question,
        "messages": [
            SystemMessage(content=SOURCE_TOOLS_PROMPT),
            HumanMessage(content=question),
        ],
        "steps": ["Source-tools mode: LLM selects PDF / database / API / MCP"],
        "documents": [],
        "tool_calls_log": [],
        "grade_summaries": [],
        "rounds": 0,
    }
    recursion_limit = max(4, settings.source_tools_max_rounds * 2 + 2)
    raw = run_graph_streaming(
        graph,
        initial,
        config=graph_tracing_config(
            "source_tools_graph",
            metadata={"question": question[:200]},
            recursion_limit=recursion_limit,
        ),
    )
    docs = list(raw.get("documents") or [])
    log = list(raw.get("tool_calls_log") or [])
    used = [str(item.get("tool")) for item in log if item.get("tool")]
    unique_used = list(dict.fromkeys(used))
    grades = [s for s in (raw.get("grade_summaries") or []) if s]
    return build_response(
        answer=str(raw.get("answer") or ""),
        mode=SOURCE_TOOLS_MODE,
        docs=docs,
        route="tools",
        route_reason=", ".join(unique_used) if unique_used else "no_tools",
        grade_summary=" | ".join(grades) if grades else None,
        steps=list(raw.get("steps") or []),
        tenant_id=(rbac_context or current_rbac()).tenant_id,
        pipeline_version="source-tools-v1",
        response_status="answered" if str(raw.get("answer") or "").strip() else "abstained",
    )
