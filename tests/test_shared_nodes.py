"""Tests for shared graph node factories used by the canonical graph."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import HumanMessage

from src.agents.router import RouteType
from src.graph.shared_nodes import (
    ClassifyOptions,
    DirectAnswerOptions,
    WebSearchOptions,
    after_node_condition,
    make_abort_node,
    make_classify_node,
    make_direct_answer_node,
    make_route_condition,
    make_web_search_node,
)
from src.resilience.node_gate import GateResult


def _route_decision(route: str, reason: str = "test reason") -> MagicMock:
    decision = MagicMock()
    decision.route.value = route
    decision.reason = reason
    return decision


class TestSharedNodeFactories:
    def test_plain_classify_sets_route_and_step(self):
        node = make_classify_node(ClassifyOptions())
        with patch("src.graph.shared_nodes.invoke_router", return_value=("retrieve", "needs docs")):
            update = node({"question": "What is RAG?"})

        assert update["route"] == "retrieve"
        assert update["route_reason"] == "needs docs"
        assert update["steps"] == ["Router → retrieve: needs docs"]

    def test_gated_classify_aborts_on_router_exception(self):
        node = make_classify_node(ClassifyOptions(gated=True, set_search_query=True))
        with patch("src.graph.shared_nodes.invoke_router", side_effect=RuntimeError("boom")):
            update = node({"question": "What is RAG?"})

        assert update["abort"] is True
        assert "Router failed" in update["abort_reason"]

    def test_gated_classify_sets_search_query_on_success(self):
        node = make_classify_node(ClassifyOptions(gated=True, set_search_query=True))
        with patch("src.graph.shared_nodes.invoke_router", return_value=("retrieve", "needs docs")):
            with patch(
                "src.graph.shared_nodes.check_route",
                return_value=GateResult.pass_(),
            ):
                update = node({"question": "What is RAG?"})

        assert update["search_query"] == "What is RAG?"

    def test_skip_router_classify_only_emits_step(self):
        node = make_classify_node(ClassifyOptions(support_skip_router=True))
        update = node(
            {
                "question": "What is RAG?",
                "skip_router": True,
                "route": "retrieve",
            }
        )
        assert update == {"steps": ["Router skipped (parent set route=retrieve)"]}

    def test_gated_direct_answer_aborts_on_short_answer(self):
        node = make_direct_answer_node(DirectAnswerOptions(gated=True, clear_documents=True))
        with patch("src.graph.shared_nodes.run_direct_answer", return_value="short"):
            with patch(
                "src.graph.shared_nodes.check_answer",
                return_value=GateResult.abort("answer_too_short", "too short"),
            ):
                update = node({"question": "Q?", "abort": False})

        assert update["abort"] is True
        assert update["documents"] == []

    def test_router_web_search_uses_apply_gate(self):
        node = make_web_search_node(WebSearchOptions(use_apply_gate=True, store_web_context=True))
        with patch(
            "src.graph.shared_nodes.run_web_search_answer",
            return_value=("[TOOL_ERROR] blocked", ""),
        ):
            with patch(
                "src.graph.shared_nodes.check_web_context",
                return_value=GateResult.abort("web_blocked", "blocked context"),
            ):
                update = node({"question": "Q?"})

        assert update["web_context"] == ""
        assert update["answer"] == ""
        assert update["documents"] == []

    def test_make_route_condition_maps_retrieve_target(self):
        condition = make_route_condition(retrieve_target="decompose", default_target="decompose")
        assert condition({"route": RouteType.RETRIEVE.value}) == "decompose"
        assert condition({"route": RouteType.DIRECT.value}) == "direct"

    def test_after_node_condition(self):
        assert after_node_condition({"abort": True}) == "abort"
        assert after_node_condition({"abort": False}) == "end"

    def test_abort_node_clears_extra_fields(self):
        node = make_abort_node(extra_fields={"documents": [], "filtered_documents": []})
        update = node({"abort_reason": "tool budget exceeded"})
        assert "Aborted: tool budget exceeded" in update["steps"][0]
        assert update["documents"] == []
        assert update["filtered_documents"] == []

    def test_direct_answer_plain_path(self):
        node = make_direct_answer_node(DirectAnswerOptions(clear_documents=True))
        with patch("src.graph.shared_nodes.run_direct_answer", return_value="Direct answer text."):
            update = node({"question": "Hi"})

        assert update["answer"] == "Direct answer text."
        assert update.get("documents") == []

    def test_web_search_stores_context(self):
        node = make_web_search_node(WebSearchOptions(store_web_context=True))
        with patch(
            "src.graph.shared_nodes.run_web_search_answer",
            return_value=("web context", "web answer"),
        ):
            with patch(
                "src.graph.shared_nodes.check_web_context",
                return_value=GateResult.pass_(),
            ):
                update = node({"question": "Q?"})

        assert update["web_context"] == "web context"
        assert update["answer"] == "web answer"

    def test_classify_with_router_chain(self):
        node = make_classify_node(ClassifyOptions())
        with patch("src.graph.shared_nodes.invoke_router", return_value=("retrieve", "needs docs")):
            update = node({"question": "What is RAG?"})

        assert update["route"] == "retrieve"
        assert update["steps"][0].startswith("Router → retrieve:")

    def test_tools_style_classify_initializes_messages(self):
        node = make_classify_node(ClassifyOptions(init_messages=True))
        with patch("src.graph.shared_nodes.router_chain") as mock_chain:
            mock_chain.invoke.return_value = _route_decision("retrieve")
            update = node({"question": "Use tools", "skip_router": False})

        assert isinstance(update["messages"][0], HumanMessage)
        assert update["messages"][0].content == "Use tools"
