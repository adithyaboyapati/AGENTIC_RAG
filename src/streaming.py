"""Progressive streaming helpers for agent steps and final-answer tokens.

When an emitter is installed (via ``stream_agent``), generate nodes push
``token`` events as the LLM streams, and graph runners push ``step`` events
as LangGraph nodes complete. Without an emitter, behavior matches the
blocking ``.invoke()`` path used by CLI / ``POST /query``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger(__name__)

StreamEvent = dict[str, Any]
EmitFn = Callable[[StreamEvent], None]


class CancelledRun(BaseException):
    """Raised inside a worker thread when the consumer has gone away.

    Subclasses ``BaseException`` (not ``Exception``) so the broad
    ``except Exception`` handlers scattered through the graph nodes cannot
    swallow a cancellation and keep the run — and the spend — going.
    """

_emitter: ContextVar[EmitFn | None] = ContextVar("stream_emitter", default=None)
_tokens_enabled: ContextVar[bool] = ContextVar("stream_tokens_enabled", default=True)


def get_emitter() -> EmitFn | None:
    return _emitter.get()


@contextmanager
def use_emitter(emit: EmitFn):
    """Install a stream event callback for the current context."""
    token = _emitter.set(emit)
    try:
        yield
    finally:
        _emitter.reset(token)


@contextmanager
def suppress_token_emit():
    """Disable answer-token emission (used for agentic subgraphs that re-generate later)."""
    token = _tokens_enabled.set(False)
    try:
        yield
    finally:
        _tokens_enabled.reset(token)


def emit_event(event: StreamEvent) -> None:
    callback = _emitter.get()
    if callback is not None:
        callback(event)


def emit_step(content: str) -> None:
    if content:
        emit_event({"type": "step", "content": content})


def emit_token(content: str) -> None:
    if content and _tokens_enabled.get():
        emit_event({"type": "token", "content": content})


def _chunk_to_text(chunk: Any) -> str:
    if chunk is None:
        return ""
    if isinstance(chunk, str):
        return chunk
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            else:
                text = getattr(block, "text", None)
                if text:
                    parts.append(str(text))
        return "".join(parts)
    return str(chunk) if chunk else ""


def stream_text(chain: Any, inputs: dict[str, Any]) -> str:
    """Run an LCEL string chain; stream tokens when an emitter is active."""
    if _emitter.get() is None:
        result = chain.invoke(inputs)
        return result if isinstance(result, str) else str(result)

    parts: list[str] = []
    try:
        for chunk in chain.stream(inputs):
            text = _chunk_to_text(chunk)
            if text:
                parts.append(text)
                emit_token(text)
    except Exception:
        logger.warning("chain.stream failed — falling back to invoke", exc_info=True)
        result = chain.invoke(inputs)
        text = result if isinstance(result, str) else str(result)
        if text:
            emit_token(text)
        return text
    return "".join(parts)


def stream_llm_message(llm: Any, messages: list) -> Any:
    """Stream a chat-model completion; emit text tokens when not tool-calling."""
    if _emitter.get() is None:
        return llm.invoke(messages)

    response = None
    saw_tool_calls = False
    try:
        for chunk in llm.stream(messages):
            response = chunk if response is None else response + chunk
            tool_chunks = getattr(chunk, "tool_call_chunks", None) or []
            if tool_chunks or getattr(chunk, "tool_calls", None):
                saw_tool_calls = True
            text = _chunk_to_text(chunk)
            # Only stream natural-language final turns (no tool calls in the message)
            if text and not saw_tool_calls:
                emit_token(text)
    except Exception:
        logger.warning("llm.stream failed — falling back to invoke", exc_info=True)
        return llm.invoke(messages)

    if response is None:
        return llm.invoke(messages)
    # If the completed message still has tool calls, do not leave stray tokens
    if getattr(response, "tool_calls", None):
        return response
    return response


def run_graph_streaming(graph: Any, initial_state: dict) -> dict:
    """Run a compiled LangGraph, emitting steps as nodes complete.

    Uses ``stream_mode="values"`` so step lists accumulate correctly under
    ``Annotated[..., operator.add]``.
    """
    final: dict | None = None
    seen_steps = 0
    for state in graph.stream(initial_state, stream_mode="values"):
        final = state
        steps = state.get("steps") or []
        if _emitter.get() is not None:
            while seen_steps < len(steps):
                emit_step(steps[seen_steps])
                seen_steps += 1
    return final if final is not None else initial_state


def iter_queue_events(event_iter: Iterator[StreamEvent | None]) -> Iterator[StreamEvent]:
    """Yield events until a ``None`` sentinel."""
    for event in event_iter:
        if event is None:
            break
        yield event
