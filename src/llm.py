"""Shared LLM client used across RAG modes and agents.

Primary provider is OpenAI. When ``GROQ_API_KEY`` is set (and fallback is
enabled), failed primary calls — including insufficient quota / rate limits —
automatically retry on Groq via LangChain ``with_fallbacks``.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI

from src.config import settings

logger = logging.getLogger(__name__)

# Set to "groq" when the secondary provider handles a call in this request.
_llm_provider_var: ContextVar[str] = ContextVar("llm_provider", default="openai")


def reset_llm_provider() -> None:
    _llm_provider_var.set("openai")


def get_llm_provider() -> str:
    return _llm_provider_var.get("openai")


def _mark_groq_fallback() -> None:
    _llm_provider_var.set("groq")
    try:
        from src.api.metrics import record_llm_fallback

        record_llm_fallback()
    except Exception:
        pass


def _build_primary() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key or None,
        temperature=0,
        # Hard limits so abandoned/runaway calls can't bill indefinitely
        timeout=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
        max_tokens=settings.max_output_tokens,
    )


def _build_fallback() -> BaseChatModel | None:
    if not settings.llm_fallback_enabled or not settings.groq_api_key:
        return None
    from langchain_groq import ChatGroq

    return ChatGroq(
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        temperature=0,
        timeout=settings.groq_timeout_seconds,
        max_retries=settings.groq_max_retries,
        max_tokens=settings.max_output_tokens,
    )


def _with_fallbacks(primary: Runnable, fallback: Runnable) -> Runnable:
    """Wire primary → secondary, logging when the secondary is used."""

    class _LoggedFallback(Runnable):
        """Thin wrapper so we can see provider failover in logs."""

        def __init__(self, inner: Runnable, label: str):
            self._inner = inner
            self._label = label

        def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
            logger.warning("Primary LLM failed; falling back to %s", self._label)
            _mark_groq_fallback()
            return self._inner.invoke(input, config=config, **kwargs)

        async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
            logger.warning("Primary LLM failed; falling back to %s", self._label)
            _mark_groq_fallback()
            return await self._inner.ainvoke(input, config=config, **kwargs)

        def stream(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
            logger.warning("Primary LLM failed; falling back to %s", self._label)
            _mark_groq_fallback()
            return self._inner.stream(input, config=config, **kwargs)

        async def astream(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
            logger.warning("Primary LLM failed; falling back to %s", self._label)
            _mark_groq_fallback()
            return self._inner.astream(input, config=config, **kwargs)

    label = getattr(fallback, "model_name", None) or settings.groq_model
    return primary.with_fallbacks([_LoggedFallback(fallback, f"groq:{label}")])


class FallbackChatModel(Runnable):
    """Chat model that preserves structured-output / tool binding with fallbacks.

    Call sites use ``get_llm().with_structured_output(...)`` and
    ``get_llm().bind_tools(...)``. Those must bind on *both* providers, then
    compose with ``with_fallbacks`` — a bare ``RunnableWithFallbacks`` does not
    expose those helpers.

    Subclasses ``Runnable`` so LCEL pipes (``prompt | get_llm() | parser``) work.
    """

    def __init__(self, primary: BaseChatModel, fallback: BaseChatModel):
        super().__init__()
        self._primary = primary
        self._fallback = fallback
        self._runnable: Runnable = _with_fallbacks(primary, fallback)
        logger.info(
            "LLM fallback enabled: %s → groq:%s",
            settings.openai_model,
            settings.groq_model,
        )

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Runnable:
        primary = self._primary.with_structured_output(schema, **kwargs)
        fallback = self._fallback.with_structured_output(schema, **kwargs)
        return _with_fallbacks(primary, fallback)

    def bind_tools(self, tools: Any, **kwargs: Any) -> Runnable:
        primary = self._primary.bind_tools(tools, **kwargs)
        fallback = self._fallback.bind_tools(tools, **kwargs)
        return _with_fallbacks(primary, fallback)

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        return self._runnable.invoke(input, config=config, **kwargs)

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        return await self._runnable.ainvoke(input, config=config, **kwargs)

    def stream(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        return self._runnable.stream(input, config=config, **kwargs)

    async def astream(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        return self._runnable.astream(input, config=config, **kwargs)

    def batch(self, inputs: Any, config: Any = None, **kwargs: Any) -> Any:
        return self._runnable.batch(inputs, config=config, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._runnable, name)


def get_llm() -> FallbackChatModel | ChatOpenAI:
    """Return the shared chat LLM (OpenAI, with optional Groq fallback)."""
    primary = _build_primary()
    fallback = _build_fallback()
    if fallback is None:
        return primary
    return FallbackChatModel(primary, fallback)
