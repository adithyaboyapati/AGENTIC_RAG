"""Tests for Phase 15: Multi-Agent Consensus & Adversarial Debate."""

from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.documents import Document

from src.api.server import app
from src.graph.consensus_graph import (
    adjudicate_node,
    ask_consensus,
    challenge_node,
    retrieve_node,
)
from src.schemas import AgentResponse
from langchain_community.chat_models.fake import FakeListChatModel


def test_consensus_retrieve_node():
    sample_docs = [
        Document(
            page_content="CRAG introduces an evaluator to assess document quality.",
            metadata={"source": "crag.pdf", "page": 1},
        )
    ]
    with patch("src.graph.consensus_graph.retrieve", return_value=sample_docs):
        state = {
            "question": "What does CRAG evaluate?",
            "documents": [],
            "sources": [],
            "context": "",
            "proposal": "",
            "critique": "",
            "critique_summary": "",
            "answer": "",
            "consensus_score": 0.0,
            "steps": [],
        }
        res = retrieve_node(state)
        assert len(res["documents"]) == 1
        assert "evaluator" in res["context"]
        assert "crag.pdf#p1" in res["sources"]
        assert len(res["steps"]) == 1


def test_consensus_propose_and_challenge_nodes():
    fake_llm = FakeListChatModel(
        responses=["Critique Summary: No unsupported claims found.\nUnsupported Claims: None."]
    )

    state = {
        "question": "What is Self-RAG?",
        "documents": [],
        "sources": ["self_rag.pdf"],
        "context": "Self-RAG trains reflection tokens.",
        "proposal": "Self-RAG introduces reflection tokens to control generation.",
        "critique": "",
        "critique_summary": "",
        "answer": "",
        "consensus_score": 0.0,
        "steps": [],
    }

    with patch("src.graph.consensus_graph.get_llm", return_value=fake_llm):
        critique_res = challenge_node(state)
        assert "critique" in critique_res
        assert "No unsupported claims found" in critique_res["critique_summary"]
        assert len(critique_res["steps"]) == 1


def test_consensus_adjudicate_node():
    fake_llm = FakeListChatModel(
        responses=[
            (
                "Final Consensus Answer: Self-RAG utilizes reflection tokens for dynamic retrieval.\n"
                "Confidence Score: 0.96\n"
                "Adjudication Summary: Proposer claims verified against context."
            )
        ]
    )

    state = {
        "question": "What is Self-RAG?",
        "documents": [],
        "sources": ["self_rag.pdf"],
        "context": "Self-RAG trains reflection tokens.",
        "proposal": "Self-RAG uses reflection tokens.",
        "critique": "No flaws found.",
        "critique_summary": "All supported",
        "answer": "",
        "consensus_score": 0.0,
        "steps": [],
    }

    with patch("src.graph.consensus_graph.get_llm", return_value=fake_llm):
        adj_res = adjudicate_node(state)
        assert "Self-RAG utilizes reflection tokens" in adj_res["answer"]
        assert adj_res["consensus_score"] == 0.96
        assert len(adj_res["steps"]) == 1


def test_ask_consensus_integration():
    sample_docs = [
        Document(
            page_content="Corrective RAG (CRAG) evaluates retrieval before generation.",
            metadata={"source": "crag.pdf", "page": 2},
        )
    ]

    fake_llm = FakeListChatModel(
        responses=[
            "Proposer: CRAG evaluates retrieval quality.",
            "Critique: No flaws.",
            "Final Consensus Answer: Corrective RAG (CRAG) evaluates retrieval quality.\nConfidence Score: 0.95",
        ]
    )

    with patch("src.graph.consensus_graph.retrieve", return_value=sample_docs), patch(
        "src.graph.consensus_graph.get_llm", return_value=fake_llm
    ):
        resp = ask_consensus("How does CRAG work?")
        assert isinstance(resp, AgentResponse)
        assert resp.mode == "consensus"
        assert "Corrective RAG" in resp.answer
        assert resp.consensus_score == 0.95
        assert len(resp.steps) >= 3


def test_consensus_api_endpoint(monkeypatch):
    monkeypatch.setattr("src.api.server.auth_required", lambda: False)
    client = TestClient(app)

    mock_resp = AgentResponse(
        answer="Consensus verified answer: Modular RAG is modular.",
        mode="consensus",
        sources=["modular.pdf#p1"],
        steps=["retrieve", "propose", "challenge", "adjudicate"],
        consensus_score=0.98,
        critique_summary="No unsupported assertions",
    )

    with patch("src.runner._dispatch", return_value=mock_resp):
        resp = client.post(
            "/query",
            json={
                "question": "What is Modular RAG?",
                "mode": "consensus",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "consensus"
        assert "Consensus verified answer" in data["answer"]
        assert data["consensus_score"] == 0.98
        assert data["critique_summary"] == "No unsupported assertions"
