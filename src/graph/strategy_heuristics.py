"""Deterministic-first strategy selection for the canonical graph."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.agents.orchestrator import StrategyChoice, choose_strategy

_COMPARE_RE = re.compile(
    r"\b(compare|versus|vs\.?|difference between|contrast|both .+ and)\b",
    re.IGNORECASE,
)
_MULTI_ENTITY_RE = re.compile(
    r"\b(and also|as well as|multiple|each of|both)\b",
    re.IGNORECASE,
)
_MULTI_HOP_RE = re.compile(
    r"\b(then|after that|step by step|first .+ then|what .+ use|how does .+ work)\b",
    re.IGNORECASE,
)
_SIMPLE_RE = re.compile(
    r"^(what is|who is|define|explain|describe)\b",
    re.IGNORECASE,
)

CANONICAL_STRATEGIES = frozenset({"simple", "decompose", "multi_hop"})


@dataclass(frozen=True)
class StrategyDecision:
    strategy: str
    decision_source: str  # heuristic | llm
    rationale: str
    confidence: float


def _clamp_strategy(strategy: str) -> str:
    normalized = (strategy or "simple").strip().lower().replace("-", "_")
    if normalized == "tools":
        return "simple"
    if normalized not in CANONICAL_STRATEGIES:
        return "simple"
    return normalized


def heuristic_strategy(question: str) -> StrategyDecision:
    text = (question or "").strip()
    if not text:
        return StrategyDecision("simple", "heuristic", "empty question defaults to simple", 1.0)

    if _COMPARE_RE.search(text) or (
        _MULTI_ENTITY_RE.search(text) and " and " in text.lower()
    ):
        return StrategyDecision(
            "decompose",
            "heuristic",
            "Comparison or multi-entity question detected",
            0.92,
        )

    if _MULTI_HOP_RE.search(text) and len(text.split()) > 8:
        return StrategyDecision(
            "multi_hop",
            "heuristic",
            "Sequential / dependent reasoning pattern detected",
            0.88,
        )

    if _SIMPLE_RE.match(text) and len(text.split()) <= 12:
        return StrategyDecision(
            "simple",
            "heuristic",
            "Short definitional question",
            0.9,
        )

    return StrategyDecision(
        "simple",
        "heuristic",
        "No strong heuristic match — low confidence",
        0.45,
    )


def select_strategy(
    question: str,
    *,
    force_strategy: str | None = None,
    llm_confidence_threshold: float = 0.75,
) -> StrategyDecision:
    """Deterministic-first strategy selection with optional LLM escalation."""
    if force_strategy:
        strategy = _clamp_strategy(force_strategy)
        return StrategyDecision(
            strategy=strategy,
            decision_source="heuristic",
            rationale=f"Forced strategy={strategy}",
            confidence=1.0,
        )

    heuristic = heuristic_strategy(question)
    if heuristic.confidence >= llm_confidence_threshold:
        return heuristic

    try:
        llm_choice: StrategyChoice = choose_strategy(question)
        strategy = _clamp_strategy(llm_choice.strategy)
        return StrategyDecision(
            strategy=strategy,
            decision_source="llm",
            rationale=llm_choice.reasoning,
            confidence=0.8,
        )
    except Exception as exc:
        return StrategyDecision(
            strategy="simple",
            decision_source="heuristic",
            rationale=f"Strategy LLM failed ({type(exc).__name__}); defaulting to simple",
            confidence=0.5,
        )
