"""Conversation memory utilities — compact history for follow-up questions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChatTurn:
    role: str  # "user" | "assistant"
    content: str


def pair_exchanges(messages: list[dict[str, str]]) -> list[tuple[str, str | None]]:
    """Pair messages into (user_question, assistant_answer|None) exchanges."""
    exchanges: list[tuple[str, str | None]] = []
    pending_user: str | None = None

    for msg in messages:
        role = msg.get("role", "")
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            if pending_user is not None:
                exchanges.append((pending_user, None))
            pending_user = content
        elif role == "assistant":
            if pending_user is not None:
                exchanges.append((pending_user, content))
                pending_user = None

    if pending_user is not None:
        exchanges.append((pending_user, None))

    return exchanges


def _truncate(text: str, max_chars: int) -> str:
    text = text.strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    # Prefer cutting on a word boundary near the limit
    cut = text[: max_chars - 1].rstrip()
    space = cut.rfind(" ")
    if space > max_chars // 2:
        cut = cut[:space]
    return cut + "…"


def format_chat_history(
    messages: list[dict[str, str]],
    max_turns: int = 6,
    *,
    recent_exchanges: int = 3,
    answer_max_chars: int = 500,
    max_older_queries: int = 10,
) -> str:
    """
    Compact conversation context for the LLM.

    - Last `recent_exchanges`: full question + answer truncated to `answer_max_chars`
    - Older exchanges: user questions only (topic trail)
    - `max_turns` kept for API compat; maps to how many message pairs we consider
      as a soft upper bound on recent+older window (2 messages ≈ 1 exchange)
    """
    if not messages:
        return ""

    # Bound input by message count (legacy max_turns ≈ messages), then pair
    bounded = messages[-max(max_turns * 2, recent_exchanges * 2 + max_older_queries * 2) :]
    exchanges = pair_exchanges(bounded)
    if not exchanges:
        return ""

    recent_n = max(0, recent_exchanges)
    recent = exchanges[-recent_n:] if recent_n else []
    older = exchanges[:-recent_n] if recent_n and len(exchanges) > recent_n else (
        exchanges if not recent_n else []
    )

    parts: list[str] = []

    if older:
        queries = [q for q, _ in older][-max_older_queries:]
        parts.append("Earlier questions (topic trail — answers omitted):")
        for i, q in enumerate(queries, 1):
            parts.append(f"{i}. {q}")

    if recent:
        if parts:
            parts.append("")
        parts.append("Recent exchanges (question + truncated answer):")
        for i, (q, a) in enumerate(recent, 1):
            parts.append(f"Q{i}: {q}")
            if a:
                parts.append(f"A{i}: {_truncate(a, answer_max_chars)}")

    return "\n".join(parts)


def augment_question_with_history(
    question: str,
    messages: list[dict[str, str]],
    *,
    max_turns: int | None = None,
    recent_exchanges: int | None = None,
    answer_max_chars: int | None = None,
    max_older_queries: int | None = None,
) -> str:
    """
    Wrap the current question with compact prior conversation context.

    Recent turns keep Q + truncated A so follow-ups stay grounded.
    Older turns keep questions only so the model can infer topic progression
    without paying for full past answers.
    """
    try:
        from src.config import settings

        max_turns = settings.memory_max_turns if max_turns is None else max_turns
        recent_exchanges = (
            settings.memory_recent_exchanges if recent_exchanges is None else recent_exchanges
        )
        answer_max_chars = (
            settings.memory_answer_max_chars if answer_max_chars is None else answer_max_chars
        )
        max_older_queries = (
            settings.memory_max_older_queries if max_older_queries is None else max_older_queries
        )
    except Exception:
        max_turns = 6 if max_turns is None else max_turns
        recent_exchanges = 3 if recent_exchanges is None else recent_exchanges
        answer_max_chars = 500 if answer_max_chars is None else answer_max_chars
        max_older_queries = 10 if max_older_queries is None else max_older_queries

    history = format_chat_history(
        messages,
        max_turns=max_turns,
        recent_exchanges=recent_exchanges,
        answer_max_chars=answer_max_chars,
        max_older_queries=max_older_queries,
    )
    if not history:
        return question

    return f"""Previous conversation:
{history}

Current question: {question}

Instructions:
- If this is a follow-up, use the conversation above for context.
- Prefer recent Q/A pairs for grounding; use earlier questions only for topic continuity.
- If the question stands alone, answer it directly."""
