"""Tests for follow-up question generation."""

from unittest.mock import MagicMock, patch

from src.agents.followups import FollowUpQuestions, generate_follow_ups
from src.runner import run_agent
from src.schemas import AgentResponse


def test_generate_follow_ups_returns_three():
    mock_result = FollowUpQuestions(
        questions=[
            "How does Self-RAG grade documents?",
            "What is the difference between CRAG and Self-RAG?",
            "When should you use modular RAG?",
        ]
    )
    with (
        patch("src.agents.followups.followup_chain") as mock_chain,
        patch("src.agents.followups.retrieve", create=True),
    ):
        mock_chain.invoke.return_value = mock_result
        with patch("src.retrieval.retriever.retrieve", return_value=[]), patch(
            "src.retrieval.retriever.format_docs", return_value=""
        ):
            out = generate_follow_ups(
                "What is Self-RAG?",
                "Self-RAG grades its own retrievals.",
                sources=["rag.pdf"],
            )
    assert len(out) == 3
    assert out[0].startswith("How does Self-RAG")


def test_generate_follow_ups_empty_answer():
    assert generate_follow_ups("What is RAG?", "", sources=["rag.pdf"]) == []


def test_generate_follow_ups_dedupes_and_skips_original():
    mock_result = MagicMock()
    mock_result.questions = [
        "What is Self-RAG?",
        "What is Self-RAG?",
        "How does Self-RAG grade documents?",
        "What fallback does CRAG use?",
        "Compare naive and modular RAG",
    ]
    with patch("src.agents.followups.followup_chain") as mock_chain:
        mock_chain.invoke.return_value = mock_result
        out = generate_follow_ups(
            "What is Self-RAG?",
            "Self-RAG grades its own retrievals.",
            sources=["web search"],
        )
    assert "What is Self-RAG?" not in out
    assert len(out) == 3
    assert out == [
        "How does Self-RAG grade documents?",
        "What fallback does CRAG use?",
        "Compare naive and modular RAG",
    ]


def test_generate_follow_ups_failure_returns_empty():
    with patch("src.agents.followups.followup_chain") as mock_chain:
        mock_chain.invoke.side_effect = RuntimeError("llm down")
        out = generate_follow_ups("What is RAG?", "RAG retrieves then generates.", sources=[])
    assert out == []


@patch("src.runner._attach_follow_ups", return_value=["Follow A?", "Follow B?", "Follow C?"])
@patch("src.runner._run_with_cost_tracking")
@patch("src.runner.InputGuardrails.validate", return_value=(True, []))
@patch("src.runner.PrivacyGuard.check_input", return_value=(True, []))
@patch("src.runner.PrivacyGuard.check_output", return_value=(True, []))
@patch("src.runner.OutputGuardrails.validate", return_value=(True, []))
@patch("src.runner.get_cost_tracker")
def test_run_agent_attaches_follow_ups(
    mock_tracker,
    _out_val,
    _priv_out,
    _priv_in,
    _in_val,
    mock_run,
    mock_attach,
):
    tracker = MagicMock()
    tracker.check_query_rate.return_value = (True, [])
    tracker.check_token_budget.return_value = (True, [])
    mock_tracker.return_value = tracker
    mock_run.return_value = AgentResponse(
        answer="RAG combines retrieval with generation.",
        mode="baseline",
        sources=["rag.pdf"],
    )

    result = run_agent("What is RAG?", "baseline", use_memory=False)
    assert result.follow_ups == ["Follow A?", "Follow B?", "Follow C?"]
    mock_attach.assert_called_once()
