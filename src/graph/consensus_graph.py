"""
Phase 15: Multi-Agent Consensus & Adversarial Debate Graph.

Orchestrates a 3-agent jury network using LangGraph:
  1. Retrieve: Fetches relevant evidence from knowledge base
  2. Propose: Drafts initial comprehensive answer grounded in context
  3. Challenge: Adversarial Critic scrutinizes claims for over-generalizations or unverified assertions
  4. Adjudicate: Consensus Judge arbitrates differences and outputs verified final answer + confidence score
"""

from __future__ import annotations

import logging
import operator
import re
from typing import Annotated, TypedDict

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import END, START, StateGraph

from src.llm import get_llm
from src.prompts import CHALLENGER_PROMPT, CONSENSUS_JUDGE_PROMPT, PROPOSER_PROMPT
from src.retrieval.citations import build_response, docs_to_sources
from src.retrieval.retriever import format_docs, retrieve
from src.schemas import AgentResponse
from src.streaming import run_graph_streaming, stream_text

logger = logging.getLogger(__name__)


class ConsensusState(TypedDict):
    question: str
    documents: list[Document]
    sources: list[str]
    context: str
    proposal: str
    critique: str
    critique_summary: str
    answer: str
    consensus_score: float
    steps: Annotated[list[str], operator.add]


def retrieve_node(state: ConsensusState) -> dict:
    """Node 1: Retrieve context documents from knowledge base."""
    docs = retrieve(state["question"])
    context = format_docs(docs, query=state["question"])
    return {
        "documents": docs,
        "sources": docs_to_sources(docs),
        "context": context,
        "steps": [f"Retrieved {len(docs)} source documents"],
    }


def propose_node(state: ConsensusState) -> dict:
    """Node 2: Proposer Agent drafts initial fact-grounded answer."""
    llm = get_llm()
    chain = PROPOSER_PROMPT | llm | StrOutputParser()
    proposal = stream_text(
        chain,
        {"question": state["question"], "context": state["context"]},
    )
    return {
        "proposal": proposal,
        "steps": ["Proposer Agent drafted initial thesis with evidentiary citations"],
    }


def challenge_node(state: ConsensusState) -> dict:
    """Node 3: Adversarial Challenger searches for ungrounded claims or missing nuances."""
    llm = get_llm()
    chain = CHALLENGER_PROMPT | llm | StrOutputParser()
    critique = chain.invoke(
        {
            "question": state["question"],
            "context": state["context"],
            "proposal": state["proposal"],
        }
    )

    # Extract brief critique summary
    summary_lines = [
        line.replace("Critique Summary:", "").strip()
        for line in critique.split("\n")
        if "Critique Summary:" in line or "Critique:" in line
    ]
    summary = summary_lines[0] if summary_lines else "Adversarial critique completed"

    return {
        "critique": critique,
        "critique_summary": summary[:150],
        "steps": [f"Challenger Agent scrutinized proposal: {summary[:100]}"],
    }


def adjudicate_node(state: ConsensusState) -> dict:
    """Node 4: Consensus Judge arbitrates debate, filters ungrounded assertions, and synthesizes final answer."""
    llm = get_llm()
    chain = CONSENSUS_JUDGE_PROMPT | llm | StrOutputParser()
    raw_judgment = stream_text(
        chain,
        {
            "question": state["question"],
            "context": state["context"],
            "proposal": state["proposal"],
            "critique": state["critique"],
        },
    )

    # Parse confidence score if mentioned in text (e.g. 0.95 or 95%)
    score = 0.92
    score_match = re.search(r"(?:Confidence(?:\s+Score)?[:=]?\s*)(0\.\d+|\d{2,3}%)", raw_judgment, re.IGNORECASE)
    if score_match:
        val_str = score_match.group(1).replace("%", "")
        try:
            val = float(val_str)
            score = val / 100.0 if val > 1.0 else val
        except ValueError:
            pass

    return {
        "answer": raw_judgment,
        "consensus_score": score,
        "steps": [f"Consensus Judge finalized synthesis (Confidence: {score:.2f})"],
    }


def build_consensus_graph():
    """Construct the LangGraph workflow for Multi-Agent Consensus."""
    workflow = StateGraph(ConsensusState)

    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("propose", propose_node)
    workflow.add_node("challenge", challenge_node)
    workflow.add_node("adjudicate", adjudicate_node)

    workflow.add_edge(START, "retrieve")
    workflow.add_edge("retrieve", "propose")
    workflow.add_edge("propose", "challenge")
    workflow.add_edge("challenge", "adjudicate")
    workflow.add_edge("adjudicate", END)

    return workflow.compile()


_consensus_graph = build_consensus_graph()


def ask_consensus(question: str) -> AgentResponse:
    """Run the Multi-Agent Consensus Debate graph on a user question."""
    final_state = run_graph_streaming(
        _consensus_graph,
        {
            "question": question,
            "documents": [],
            "sources": [],
            "context": "",
            "proposal": "",
            "critique": "",
            "critique_summary": "",
            "answer": "",
            "consensus_score": 0.0,
            "steps": [],
        },
    )

    resp = build_response(
        answer=final_state.get("answer", ""),
        docs=final_state.get("documents", []),
        mode="consensus",
        steps=final_state.get("steps", []),
    )
    resp.consensus_score = final_state.get("consensus_score")
    resp.critique_summary = final_state.get("critique_summary")
    return resp
