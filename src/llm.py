"""Shared LLM client used across RAG modes and agents."""

from langchain_openai import ChatOpenAI

from src.config import settings


def get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key or None,
        temperature=0,
        # Hard limits so abandoned/runaway calls can't bill indefinitely
        timeout=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
        max_tokens=settings.max_output_tokens,
    )
