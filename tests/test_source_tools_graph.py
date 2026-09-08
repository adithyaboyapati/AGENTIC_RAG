"""LLM-selected source tools mode (PDF / DB / API / MCP / calculator)."""

from __future__ import annotations

from unittest.mock import patch

from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from src.agents.grader import DocumentGrade, GradingResult
from src.graph.source_tools_graph import (
    SOURCE_TOOLS_MODE,
    ask_source_tools,
    reset_source_tools_graph,
)
from src.runner import _dispatch, build_pipeline_payload
from src.schemas import AgentResponse


class _ScriptedLLM:
    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)

    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, input, config=None, **kwargs):
        return self._responses.pop(0)

    def stream(self, input, config=None, **kwargs):
        yield self.invoke(input, config=config, **kwargs)


def _mcp_doc() -> Document:
    return Document(
        page_content="Experiment 42 concluded that parent-child chunking improved nDCG by 12%.",
        metadata={
            "source": "mcp:exp-42",
            "source_type": "mcp",
            "chunk_id": "mcp-exp-42",
            "section_title": "exp-42",
            "score": 0.91,
        },
    )


def _keep_all(question: str, documents: list[Document]):
    grades = [
        DocumentGrade(chunk_index=i, relevant=True, score=0.91, reason="relevant")
        for i, _ in enumerate(documents, 1)
    ]
    return list(documents), GradingResult(grades=grades)


def _mcp_then_answer() -> list[AIMessage]:
    return [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "query_mcp",
                    "args": {"query": "exp-42 chunking"},
                    "id": "call_mcp",
                    "type": "tool_call",
                }
            ],
        ),
        AIMessage(content="Experiment 42 found a 12% nDCG gain from parent-child chunking [1]."),
    ]


def test_source_tools_calls_mcp_then_answers(monkeypatch):
    reset_source_tools_graph()
    llm = _ScriptedLLM(_mcp_then_answer())
    monkeypatch.setattr("src.graph.source_tools_graph.get_llm", lambda: llm)
    with (
        patch("src.graph.source_tools_graph._docs_for_call", return_value=[_mcp_doc()]),
        patch("src.graph.source_tools_graph.grade_documents", side_effect=_keep_all),
    ):
        result = ask_source_tools("What did experiment 42 conclude about chunking?")

    assert result.mode == SOURCE_TOOLS_MODE
    assert result.route == "tools"
    assert "query_mcp" in (result.route_reason or "")
    assert "12%" in result.answer
    assert result.citations
    assert result.citations[0].chunk_id == "mcp-exp-42"
    assert any(step.startswith("Tool → query_mcp") for step in result.steps)
    assert any(step.startswith("Graded query_mcp") for step in result.steps)
    assert "1/1 chunks relevant" in (result.grade_summary or "")


def test_source_tools_calculator_path(monkeypatch):
    reset_source_tools_graph()
    llm = _ScriptedLLM(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "calculator",
                        "args": {"expression": "80+90*9000"},
                        "id": "call_calc",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="80 + 90 * 9000 = 810080."),
        ]
    )
    monkeypatch.setattr("src.graph.source_tools_graph.get_llm", lambda: llm)
    result = ask_source_tools("what is 80+90*9000")
    assert result.route == "tools"
    assert "calculator" in (result.route_reason or "")
    assert "810080" in result.answer
    assert any("calculator" in step for step in result.steps)
    assert result.grade_summary is None
    assert not any(step.startswith("Graded") for step in result.steps)


def test_dispatch_uses_source_tools_graph():
    fake = AgentResponse(answer="ok", mode=SOURCE_TOOLS_MODE, route="tools")
    with patch("src.graph.source_tools_graph.ask_source_tools", return_value=fake) as mock_ask:
        result = _dispatch("Who owns retriever-prod?", SOURCE_TOOLS_MODE)
    mock_ask.assert_called_once()
    assert result.mode == SOURCE_TOOLS_MODE


def test_pipeline_payload_includes_tool_stage():
    result = AgentResponse(
        answer="810080",
        mode="source_tools",
        route="tools",
        route_reason="calculator",
        steps=["Tool agent round 1: choosing sources", "Tool → calculator(80+90*9000) [ok]"],
    )
    payload = build_pipeline_payload(
        question="what is 80+90*9000",
        mode="source_tools",
        result=result,
        sanitized_question="what is 80+90*9000",
        effective_question="what is 80+90*9000",
        latency_ms=12.0,
    )
    tools = next(s for s in payload["stages"] if s["id"] == "tools")
    assert tools["status"] == "complete"
    assert any("calculator" in c for c in tools["data"]["calls"])
    rerank = next(s for s in payload["stages"] if s["id"] == "rerank")
    assert rerank["status"] == "skipped"


def test_source_tools_drops_irrelevant_chunks(monkeypatch):
    reset_source_tools_graph()
    llm = _ScriptedLLM(_mcp_then_answer())
    monkeypatch.setattr("src.graph.source_tools_graph.get_llm", lambda: llm)
    noise = Document(
        page_content="Unrelated weather forecast for Tuesday.",
        metadata={
            "source": "mcp:noise",
            "source_type": "mcp",
            "chunk_id": "mcp-noise",
            "section_title": "noise",
            "score": 0.4,
        },
    )
    grading = GradingResult(
        grades=[
            DocumentGrade(chunk_index=1, relevant=True, score=0.95, reason="experiment"),
            DocumentGrade(chunk_index=2, relevant=False, score=0.1, reason="noise"),
        ]
    )
    with (
        patch(
            "src.graph.source_tools_graph._docs_for_call",
            return_value=[_mcp_doc(), noise],
        ),
        patch(
            "src.graph.source_tools_graph.grade_documents",
            return_value=([_mcp_doc()], grading),
        ),
    ):
        result = ask_source_tools("What did experiment 42 conclude about chunking?")

    assert [c.chunk_id for c in result.citations] == ["mcp-exp-42"]
    assert "1/2 chunks relevant" in (result.grade_summary or "")
    assert any("Graded query_mcp" in step for step in result.steps)

    payload = build_pipeline_payload(
        question="What did experiment 42 conclude about chunking?",
        mode="source_tools",
        result=result,
        sanitized_question="What did experiment 42 conclude about chunking?",
        effective_question="What did experiment 42 conclude about chunking?",
        latency_ms=12.0,
    )
    rerank = next(s for s in payload["stages"] if s["id"] == "rerank")
    assert rerank["status"] == "complete"
    assert "1/2" in (rerank["data"]["grade_summary"] or "")


def test_source_tools_all_graded_out_has_no_citations(monkeypatch):
    reset_source_tools_graph()
    llm = _ScriptedLLM(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "query_mcp",
                        "args": {"query": "exp-42 chunking"},
                        "id": "call_mcp",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="I could not find relevant lab notes after grading."),
        ]
    )
    monkeypatch.setattr("src.graph.source_tools_graph.get_llm", lambda: llm)
    grading = GradingResult(
        grades=[DocumentGrade(chunk_index=1, relevant=False, score=0.05, reason="off-topic")]
    )
    with (
        patch("src.graph.source_tools_graph._docs_for_call", return_value=[_mcp_doc()]),
        patch(
            "src.graph.source_tools_graph.grade_documents",
            return_value=([], grading),
        ),
    ):
        result = ask_source_tools("What did experiment 42 conclude about chunking?")

    assert result.citations == []
    assert "0/1 chunks relevant" in (result.grade_summary or "")
    assert any("Graded query_mcp" in step for step in result.steps)
