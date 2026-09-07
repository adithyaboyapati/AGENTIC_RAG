"""Shared LangGraph node primitives used across mode graphs.

Each factory returns a node or condition function configured for a specific
graph's state contract. Graph files remain wiring layers; behavioral
differences are expressed through factory options rather than copy-paste.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import HumanMessage

from src.agents.router import RouteType, router_chain
from src.chains.generation import direct_chain, web_search_chain
from src.resilience.node_gate import (
    abort_user_message,
    apply_gate,
    check_answer,
    check_route,
    check_web_context,
)
from src.streaming import stream_text
from src.tools.web_search import web_search

GraphState = Mapping[str, Any]
StateUpdate = dict[str, Any]


def get_question(state: GraphState) -> str:
    return str(state["question"])


def is_aborted(state: GraphState) -> bool:
    return bool(state.get("abort"))


def router_step(route: str, reason: str) -> str:
    return f"Router → {route}: {reason}"


def invoke_router(question: str) -> tuple[str, str]:
    decision = router_chain.invoke({"question": question})
    return decision.route.value, decision.reason


def run_direct_answer(question: str) -> str:
    return stream_text(direct_chain, {"question": question})


def run_web_search_answer(question: str) -> tuple[str, str]:
    context = web_search.invoke(question)
    from src.tools.safe_web import validate_web_search_egress

    blocked = validate_web_search_egress(str(context or ""))
    if blocked:
        context = (
            str(context or "")
            + "\n\n[Blocked unsafe URLs in search results: "
            + ", ".join(blocked[:5])
            + "]"
        )
    answer = stream_text(
        web_search_chain, {"context": context, "question": question}
    )
    return str(context) if context is not None else "", answer


def abort_if_active(state: GraphState) -> StateUpdate | None:
    if is_aborted(state):
        return {}
    return None


def gate_abort_update(
    gate,
    *,
    route: str = "",
    route_reason: str = "",
    extra: StateUpdate | None = None,
) -> StateUpdate:
    update: StateUpdate = {
        "abort": True,
        "abort_reason": gate.message,
        "steps": [f"Node gate abort [{gate.code}]: {gate.message}"],
    }
    if route:
        update["route"] = route
    if route_reason:
        update["route_reason"] = route_reason
    if extra:
        update.update(extra)
    return update


def router_exception_update(exc: Exception, *, extra: StateUpdate | None = None) -> StateUpdate:
    update: StateUpdate = {
        "abort": True,
        "abort_reason": f"Router failed: {type(exc).__name__}",
        "steps": [f"Node gate abort [router_exception]: {type(exc).__name__}"],
    }
    if extra:
        update.update(extra)
    return update


@dataclass(frozen=True)
class ClassifyOptions:
    """Configuration for classify_node factory."""

    support_skip_router: bool = False
    validate_skip_route: bool = False
    gated: bool = False
    set_search_query: bool = False
    init_messages: bool = False


def make_classify_node(options: ClassifyOptions) -> Callable[[GraphState], StateUpdate]:
    """Build a classify node for graphs that share router_chain routing."""

    def classify_node(state: GraphState) -> StateUpdate:
        question = get_question(state)

        if options.support_skip_router and state.get("skip_router") and state.get("route"):
            if options.validate_skip_route:
                gate = check_route(str(state["route"]))
                if not gate.ok:
                    extra: StateUpdate = {}
                    if options.init_messages:
                        extra["messages"] = [HumanMessage(content=question)]
                    return gate_abort_update(gate, extra=extra)
            update: StateUpdate = {
                "steps": [f"Router skipped (parent set route={state['route']})"],
            }
            if options.init_messages:
                update["messages"] = [HumanMessage(content=question)]
            return update

        if not options.gated:
            route, reason = invoke_router(question)
            update = {
                "route": route,
                "route_reason": reason,
                "steps": [router_step(route, reason)],
            }
            if options.set_search_query:
                update["search_query"] = question
            if options.init_messages:
                update["messages"] = [HumanMessage(content=question)]
            return update

        extra_on_fail: StateUpdate = {}
        if options.init_messages:
            extra_on_fail["messages"] = [HumanMessage(content=question)]

        try:
            route, reason = invoke_router(question)
        except Exception as exc:
            return router_exception_update(exc, extra=extra_on_fail)

        gate = check_route(route)
        if not gate.ok:
            return gate_abort_update(
                gate,
                route=route,
                route_reason=reason,
                extra=extra_on_fail,
            )

        update = {
            "route": route,
            "route_reason": reason,
            "steps": [router_step(route, reason)],
        }
        if options.set_search_query:
            update["search_query"] = question
        if options.init_messages:
            update["messages"] = [HumanMessage(content=question)]
        return update

    return classify_node


@dataclass(frozen=True)
class DirectAnswerOptions:
    """Configuration for direct_answer_node factory."""

    gated: bool = False
    step_message: str = "Direct answer (no retrieval)"
    clear_documents: bool = False
    clear_filtered_documents: bool = False


def make_direct_answer_node(
    options: DirectAnswerOptions,
) -> Callable[[GraphState], StateUpdate]:
    """Build a direct-answer node."""

    def direct_answer_node(state: GraphState) -> StateUpdate:
        if options.gated:
            early = abort_if_active(state)
            if early is not None:
                return early

        answer = run_direct_answer(get_question(state))

        if not options.gated:
            update: StateUpdate = {
                "answer": answer,
                "sources": [],
                "steps": [options.step_message],
            }
            if options.clear_documents:
                update["documents"] = []
            return update

        gate = check_answer(answer, required=True)
        if not gate.ok:
            fail: StateUpdate = {
                "abort": True,
                "abort_reason": gate.message,
                "answer": "",
                "sources": [],
                "steps": [f"Node gate abort [{gate.code}]: {gate.message}"],
            }
            if options.clear_documents:
                fail["documents"] = []
            if options.clear_filtered_documents:
                fail["filtered_documents"] = []
            return fail

        update = {
            "answer": answer,
            "sources": [],
            "steps": [options.step_message],
        }
        if options.clear_documents:
            update["documents"] = []
        if options.clear_filtered_documents:
            update["filtered_documents"] = []
        return update

    return direct_answer_node


@dataclass(frozen=True)
class WebSearchOptions:
    """Configuration for web_search_node factory."""

    gated: bool = False
    use_apply_gate: bool = False
    store_web_context: bool = False
    sources_label: str = "web search"
    step_message: str = "Web search + generated answer"
    blocked_step_prefix: str = "web path blocked"


def make_web_search_node(options: WebSearchOptions) -> Callable[[GraphState], StateUpdate]:
    """Build a web-search node."""

    def web_search_node(state: GraphState) -> StateUpdate:
        if options.gated:
            early = abort_if_active(state)
            if early is not None:
                return early

        question = get_question(state)
        context, answer = run_web_search_answer(question)

        if options.use_apply_gate:
            gate = check_web_context(context)
            if not gate.ok:
                return apply_gate(
                    {
                        "web_context": "",
                        "answer": "",
                        "sources": [],
                        "documents": [],
                    },
                    gate,
                    poison_keys=["web_context", "answer"],
                )
            return {
                "web_context": context,
                "answer": answer,
                "sources": [options.sources_label],
                "documents": [],
                "steps": [options.step_message],
            }

        if options.gated:
            ctx_gate = check_web_context(context)
            if not ctx_gate.ok:
                return {
                    "abort": True,
                    "abort_reason": ctx_gate.message,
                    "answer": "",
                    "sources": [],
                    "documents": [],
                    "steps": [
                        f"Node gate abort [{ctx_gate.code}]: "
                        f"{options.blocked_step_prefix} — {ctx_gate.message}"
                    ],
                }
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

        update: StateUpdate = {
            "answer": answer,
            "sources": [options.sources_label],
            "steps": [options.step_message],
        }
        if options.store_web_context:
            update["web_context"] = context
        if options.gated or options.use_apply_gate:
            update["documents"] = []
        return update

    return web_search_node


def make_abort_node(*, extra_fields: StateUpdate | None = None) -> Callable[[GraphState], StateUpdate]:
    """Build an abort node that clears graph-specific fields."""

    def abort_node(state: GraphState) -> StateUpdate:
        reason = state.get("abort_reason") or "a required step failed"
        update: StateUpdate = {
            "answer": abort_user_message(reason),
            "sources": [],
            "steps": [f"Aborted: {reason}"],
        }
        if extra_fields:
            update.update(extra_fields)
        return update

    return abort_node


def after_node_condition(state: GraphState) -> Literal["abort", "end"]:
    """Shared terminal condition for gated graphs."""
    return "abort" if is_aborted(state) else "end"


def passthrough_route_condition(state: GraphState) -> str:
    """Router graph: conditional edge key is the route value itself."""
    return str(state["route"])


def make_route_condition(
    *,
    retrieve_target: str,
    support_abort: bool = False,
    default_target: str | None = None,
) -> Callable[[GraphState], str]:
    """Build a route condition mapping router outputs to graph-specific targets."""

    def route_condition(state: GraphState) -> str:
        if support_abort and is_aborted(state):
            return "abort"
        route = state.get("route") or ""
        if route == RouteType.DIRECT.value:
            return "direct"
        if route == RouteType.WEB_SEARCH.value:
            return "web_search"
        if route == RouteType.RETRIEVE.value:
            return retrieve_target
        if support_abort:
            return "abort"
        return default_target if default_target is not None else retrieve_target

    return route_condition
