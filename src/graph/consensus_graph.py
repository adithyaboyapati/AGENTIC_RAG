"""
Phase 8: Multi-Agent Consensus & Adversarial Debate Graph.

Orchestrates a 3-agent jury network using LangGraph:
  1. Retrieve: Fetches relevant evidence from knowledge base
  2. Propose: Drafts initial answer grounded in context (or we abstain)
  3. Challenge: Adversarial Critic flags claims not in the retrieved chunks
  4. Adjudicate: Consensus Judge strips ungrounded assertions; lexical backstop drops leftovers
"""

from __future__ import annotations

import logging
import operator
import re
from typing import Annotated, Literal, TypedDict

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

ABSTAIN_ANSWER = (
    "The retrieved context does not contain enough information to answer this "
    "question. I am not adding examples, metrics, or trade-offs that are not "
    "stated in the sources."
)

_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_%+-]*")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
# Only the judge's score line — never a bare "30%" inside the answer body.
_SCORE_LINE_RE = re.compile(
    r"(?:^|\n)\s*(?:\d+\.\s*)?Confidence(?:\s+Score)?\s*[:=]\s*"
    r"(1(?:\.0+)?|0(?:\.\d+)?|\d{1,3}%)",
    re.IGNORECASE,
)
_FINAL_ANSWER_RE = re.compile(
    r"(?:^|\n)\s*(?:\d+\.\s*)?Final Consensus Answer\s*:?\s*(.*?)"
    r"(?=(?:^|\n)\s*(?:\d+\.\s*)?(?:Confidence(?:\s+Score)?|Adjudication Summary)\b|$)",
    re.IGNORECASE | re.DOTALL,
)
_UNSUPPORTED_NONE_RE = re.compile(
    r"Unsupported Claims:\s*(None|N/?A|No(?:\s+unsupported)?(?:\s+claims)?)\b",
    re.IGNORECASE,
)
_UNSUPPORTED_LISTED_RE = re.compile(r"Unsupported Claims:\s*(\S.+)", re.IGNORECASE)
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is",
    "it", "of", "on", "or", "that", "the", "this", "to", "with", "can",
    "may", "not", "its", "into", "than", "also", "such",
}

# Sentence kept only if this fraction of its content tokens appear in the context.
_MIN_SENTENCE_OVERLAP = 0.28
# If this fraction of sentences is dropped, treat the answer as ungrounded.
_ABSTAIN_DROP_RATIO = 0.55


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


def _content_tokens(text: str) -> set[str]:
    return {
        tok.lower()
        for tok in _WORD_RE.findall(text or "")
        if len(tok) > 2 and tok.lower() not in _STOPWORDS
    }


def _split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_RE.split((text or "").strip()) if p.strip()]
    return parts or ([text.strip()] if (text or "").strip() else [])


def extract_final_answer(raw: str) -> str:
    """Keep the user-facing answer; drop judge metadata that can overclaim grounding."""
    text = (raw or "").strip()
    if not text:
        return ""
    match = _FINAL_ANSWER_RE.search(text)
    if match:
        text = match.group(1).strip()
    text = re.sub(
        r"\n\s*(?:\d+\.\s*)?(?:Confidence(?:\s+Score)?\s*:.*|Adjudication Summary\s*:.*)\s*$",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return text.strip()


def parse_confidence_score(raw: str) -> float | None:
    match = _SCORE_LINE_RE.search(raw or "")
    if not match:
        return None
    val_str = match.group(1).replace("%", "")
    try:
        val = float(val_str)
    except ValueError:
        return None
    score = val / 100.0 if val > 1.0 else val
    return max(0.0, min(1.0, score))


def critique_flagged_unsupported(critique: str) -> bool:
    text = critique or ""
    if _UNSUPPORTED_NONE_RE.search(text):
        return False
    listed = _UNSUPPORTED_LISTED_RE.search(text)
    if not listed:
        return False
    body = listed.group(1).strip()
    return bool(body) and not body.lower().startswith("none")


def filter_ungrounded_sentences(answer: str, context: str) -> tuple[str, int, int]:
    """Drop answer sentences whose content tokens barely overlap the retrieved context."""
    sentences = _split_sentences(answer)
    if not sentences:
        return answer, 0, 0
    ctx_tokens = _content_tokens(context)
    if not ctx_tokens:
        return "", len(sentences), len(sentences)

    kept: list[str] = []
    dropped = 0
    for sent in sentences:
        tokens = _content_tokens(sent)
        if not tokens:
            kept.append(sent)
            continue
        overlap = len(tokens & ctx_tokens) / len(tokens)
        if overlap < _MIN_SENTENCE_OVERLAP:
            dropped += 1
            continue
        kept.append(sent)
    return " ".join(kept).strip(), dropped, len(sentences)


def finalize_judgment(raw: str, context: str, critique: str = "") -> tuple[str, float, str]:
    """Parse judge output, drop weakly grounded sentences, and cap the self-score."""
    answer = extract_final_answer(raw)
    score = parse_confidence_score(raw)
    if score is None:
        score = 0.5
        note = "confidence unstated; defaulted to 0.50"
    else:
        note = f"judge score {score:.2f}"

    if critique_flagged_unsupported(critique):
        score = min(score, 0.7)
        note += "; capped after unsupported flags"

    filtered, dropped, total = filter_ungrounded_sentences(answer, context)
    if total and dropped:
        drop_ratio = dropped / total
        score = min(score, max(0.15, 1.0 - 0.7 * drop_ratio))
        note += f"; dropped {dropped}/{total} low-overlap sentences"
        if drop_ratio >= _ABSTAIN_DROP_RATIO or not filtered:
            return ABSTAIN_ANSWER, min(score, 0.35), note + "; abstained"
        answer = filtered
    elif not (answer or "").strip():
        return ABSTAIN_ANSWER, 0.2, "empty judge answer; abstained"

    lower = answer.lower()
    if "does not contain" in lower or "not provided" in lower or "not in the" in lower:
        score = min(score, 0.6)

    score = round(score, 2)
    return _apply_confidence_caveat(answer, score), score, note


def _apply_confidence_caveat(answer: str, score: float) -> str:
    """Surface a warning when the (possibly capped) score is below the configured floor."""
    if not answer or answer == ABSTAIN_ANSWER:
        return answer
    try:
        from src.config import settings

        threshold = float(settings.consensus_min_confidence)
    except Exception:
        return answer
    if score >= threshold:
        return answer
    return (
        f"{answer.rstrip()}\n\n"
        f"_Note: consensus confidence ({score:.0%}) is below the "
        f"configured {threshold:.0%} threshold. Treat remaining claims as "
        f"incompletely grounded._"
    )


def retrieve_node(state: ConsensusState) -> dict:
    """Node 1: Retrieve context documents from knowledge base."""
    docs = retrieve(state["question"])
    docs, dropped = _drop_injected_documents(docs)
    context = format_docs(docs, query=state["question"])
    steps = [f"Retrieved {len(docs)} source documents"]
    if dropped:
        steps.append(f"Dropped {dropped} documents flagged for indirect injection")
    return {
        "documents": docs,
        "sources": docs_to_sources(docs),
        "context": context,
        "steps": steps,
    }


def _drop_injected_documents(docs: list[Document]) -> tuple[list[Document], int]:
    """Do not feed poisoned retrieved chunks into the three-agent debate."""
    if not docs:
        return [], 0
    try:
        from src.resilience.node_gate import check_indirect_injection
    except Exception:
        return docs, 0

    clean: list[Document] = []
    dropped = 0
    for i, doc in enumerate(docs):
        gate = check_indirect_injection(getattr(doc, "page_content", ""), f"document[{i}]")
        if gate.ok:
            clean.append(doc)
        else:
            dropped += 1
    return clean, dropped


def _has_evidence(state: ConsensusState) -> Literal["propose", "abstain"]:
    if state.get("documents") and (state.get("context") or "").strip():
        return "propose"
    return "abstain"


def abstain_node(state: ConsensusState) -> dict:
    """Skip the debate when retrieval returned nothing to ground against."""
    return {
        "proposal": "",
        "critique": "",
        "critique_summary": "No retrieved evidence — debate skipped",
        "answer": ABSTAIN_ANSWER,
        "consensus_score": 0.0,
        "steps": ["Abstain: no retrieved documents to ground a debate"],
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
        "steps": ["Proposer Agent drafted a context-grounded thesis"],
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
    """Node 4: Consensus Judge filters ungrounded assertions; lexical overlap is a backstop."""
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

    answer, score, note = finalize_judgment(
        raw_judgment,
        state.get("context") or "",
        state.get("critique") or "",
    )
    logger.info("consensus adjudicate | %s | score=%.2f", note, score)
    return {
        "answer": answer,
        "consensus_score": score,
        "steps": [f"Consensus Judge finalized grounded synthesis ({note})"],
    }


def build_consensus_graph():
    """Construct the LangGraph workflow for Multi-Agent Consensus."""
    workflow = StateGraph(ConsensusState)

    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("propose", propose_node)
    workflow.add_node("challenge", challenge_node)
    workflow.add_node("adjudicate", adjudicate_node)
    workflow.add_node("abstain", abstain_node)

    workflow.add_edge(START, "retrieve")
    workflow.add_conditional_edges(
        "retrieve",
        _has_evidence,
        {"propose": "propose", "abstain": "abstain"},
    )
    workflow.add_edge("propose", "challenge")
    workflow.add_edge("challenge", "adjudicate")
    workflow.add_edge("adjudicate", END)
    workflow.add_edge("abstain", END)

    return workflow.compile()


_consensus_graph = None


def get_consensus_graph():
    """Lazy singleton — matches the other mode graphs."""
    global _consensus_graph
    if _consensus_graph is None:
        _consensus_graph = build_consensus_graph()
    return _consensus_graph


def ask_consensus(question: str) -> AgentResponse:
    """Run the Multi-Agent Consensus Debate graph on a user question."""
    final_state = run_graph_streaming(
        get_consensus_graph(),
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
