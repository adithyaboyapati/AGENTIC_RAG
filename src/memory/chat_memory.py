"""Conversation memory utilities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChatTurn:
    role: str  # "user" | "assistant"
    content: str


def format_chat_history(messages: list[dict[str, str]], max_turns: int = 6) -> str:
    """Format recent messages as text for prompt injection."""
    if not messages:
        return ""

    recent = messages[-max_turns:]
    lines: list[str] = []
    for msg in recent:
        role = msg.get("role", "user").title()
        content = msg.get("content", "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def augment_question_with_history(question: str, messages: list[dict[str, str]]) -> str:
    """
    Wrap the current question with prior conversation context.

    Agents receive this augmented question so follow-ups like
    "explain more" or "what about CRAG?" work correctly.
    """
    history = format_chat_history(messages)
    if not history:
        return question

    return f"""Previous conversation:
{history}

Current question: {question}

Instructions:
- If this is a follow-up, use the conversation above for context.
- If the question stands alone, answer it directly."""
