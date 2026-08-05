"""
Phase 8: RAGAS-Inspired Metrics using LLM-as-Judge.

Evaluates RAG responses across 3 key dimensions:
  1. Faithfulness: Is answer grounded in context (no hallucinations)?
  2. Answer Relevance: Does answer address the question?
  3. Context Precision: Are retrieved docs relevant to query?
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from src.llm import get_llm
from src.prompts import ChatPromptTemplate


@dataclass
class RAGMetrics:
    """RAGAS-style evaluation metrics."""

    question: str
    answer: str
    context: str
    faithfulness: float
    answer_relevance: float
    context_precision: float

    @property
    def overall_score(self) -> float:
        """Average of all metrics."""
        return (self.faithfulness + self.answer_relevance + self.context_precision) / 3


class FaithfulnessScore(BaseModel):
    """Is answer faithful to context?"""

    score: float = Field(ge=0.0, le=1.0, description="Faithfulness 0-1")
    reasoning: str = Field(description="Why this score")


class RelevanceScore(BaseModel):
    """Does answer address question?"""

    score: float = Field(ge=0.0, le=1.0, description="Relevance 0-1")
    reasoning: str = Field(description="Why this score")


class PrecisionScore(BaseModel):
    """Are retrieved docs relevant?"""

    score: float = Field(ge=0.0, le=1.0, description="Precision 0-1")
    reasoning: str = Field(description="Why this score")


FAITHFULNESS_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """Evaluate if the answer is faithful to the provided context.
Faithfulness = answer is grounded in context, no hallucinations, no contradictions.
Score 1.0 if fully faithful, 0.0 if mostly hallucinated, 0.5 if mixed.""",
        ),
        ("human", "Context:\n{context}\n\nQuestion: {question}\n\nAnswer: {answer}\n\nScore this answer's faithfulness (0-1)."),
    ]
)

RELEVANCE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """Evaluate if the answer addresses the question.
Relevance = answer directly responds to question, covers key aspects.
Score 1.0 if fully relevant, 0.0 if off-topic, 0.5 if partially relevant.""",
        ),
        ("human", "Question: {question}\n\nAnswer: {answer}\n\nScore this answer's relevance to the question (0-1)."),
    ]
)

PRECISION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """Evaluate the precision of retrieved documents.
Precision = what fraction of retrieved docs are relevant to the question?
Score as: (# relevant docs) / (total docs).""",
        ),
        ("human", "Question: {question}\n\nRetrieved documents:\n{context}\n\nWhat fraction are relevant? (0-1)"),
    ]
)

faithfulness_chain = FAITHFULNESS_PROMPT | get_llm().with_structured_output(FaithfulnessScore)
relevance_chain = RELEVANCE_PROMPT | get_llm().with_structured_output(RelevanceScore)
precision_chain = PRECISION_PROMPT | get_llm().with_structured_output(PrecisionScore)


def evaluate_metrics(question: str, answer: str, context: str) -> RAGMetrics:
    """Evaluate a RAG response across RAGAS metrics."""
    try:
        faithfulness = faithfulness_chain.invoke({"question": question, "answer": answer, "context": context}).score
    except Exception as e:
        print(f"⚠️ Faithfulness eval failed: {e}")
        faithfulness = 0.5

    try:
        relevance = relevance_chain.invoke({"question": question, "answer": answer}).score
    except Exception as e:
        print(f"⚠️ Relevance eval failed: {e}")
        relevance = 0.5

    try:
        precision = precision_chain.invoke({"question": question, "context": context}).score
    except Exception as e:
        print(f"⚠️ Precision eval failed: {e}")
        precision = 0.5

    return RAGMetrics(
        question=question,
        answer=answer,
        context=context,
        faithfulness=faithfulness,
        answer_relevance=relevance,
        context_precision=precision,
    )
