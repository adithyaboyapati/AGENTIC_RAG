"""Shared lexical matching for extra knowledge sources."""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "what",
        "which",
        "who",
        "whom",
        "whose",
        "how",
        "when",
        "where",
        "why",
        "does",
        "do",
        "did",
        "can",
        "could",
        "should",
        "would",
        "with",
        "from",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "into",
        "about",
        "than",
        "then",
        "their",
        "there",
        "have",
        "has",
        "had",
        "not",
        "but",
        "by",
        "at",
        "as",
        "if",
        "we",
        "you",
        "your",
        "our",
        "me",
        "my",
        "please",
        "tell",
        "give",
        "show",
        "find",
        "look",
        "up",
        "vs",
        "versus",
    }
)


def normalize_token(token: str) -> str:
    value = (token or "").strip().lower()
    if len(value) > 4 and value.endswith("s") and not value.endswith("ss"):
        value = value[:-1]
    return value


def tokenize(text: str) -> set[str]:
    """Alphanumeric tokens minus stopwords, with light plural stemming."""
    tokens: set[str] = set()
    for raw in _TOKEN_RE.findall((text or "").lower()):
        if raw in STOPWORDS or len(raw) < 2:
            continue
        tokens.add(normalize_token(raw))
    return tokens


def lexical_score(query: str, text: str) -> float:
    """Fraction of query tokens that appear in ``text`` (0–1)."""
    query_tokens = tokenize(query)
    if not query_tokens:
        return 0.0
    doc_tokens = tokenize(text)
    if not doc_tokens:
        return 0.0
    overlap = query_tokens & doc_tokens
    return len(overlap) / len(query_tokens)
