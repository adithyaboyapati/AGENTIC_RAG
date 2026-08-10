"""Tests for primary → Groq LLM fallback wiring."""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, Field

from src.llm import FallbackChatModel, get_llm


class _DummySchema(BaseModel):
    answer: str = Field(description="short answer")


def test_get_llm_without_groq_returns_openai_only(monkeypatch):
    monkeypatch.setattr("src.llm.settings.groq_api_key", "")
    monkeypatch.setattr("src.llm.settings.llm_fallback_enabled", True)
    llm = get_llm()
    assert not isinstance(llm, FallbackChatModel)
    assert llm.model_name == "gpt-4o-mini" or getattr(llm, "model", None)


def test_get_llm_with_groq_wraps_fallback(monkeypatch):
    monkeypatch.setattr("src.llm.settings.groq_api_key", "gsk-test")
    monkeypatch.setattr("src.llm.settings.llm_fallback_enabled", True)
    monkeypatch.setattr("src.llm.settings.groq_model", "llama-3.3-70b-versatile")

    with patch("langchain_groq.ChatGroq") as mock_groq:
        mock_groq.return_value = MagicMock(name="ChatGroq")
        llm = get_llm()

    assert isinstance(llm, FallbackChatModel)
    mock_groq.assert_called_once()
    kwargs = mock_groq.call_args.kwargs
    assert kwargs["model"] == "llama-3.3-70b-versatile"
    assert kwargs["api_key"] == "gsk-test"
    assert kwargs["temperature"] == 0


def test_get_llm_fallback_disabled_even_with_key(monkeypatch):
    monkeypatch.setattr("src.llm.settings.groq_api_key", "gsk-test")
    monkeypatch.setattr("src.llm.settings.llm_fallback_enabled", False)
    llm = get_llm()
    assert not isinstance(llm, FallbackChatModel)


def test_fallback_invoked_when_primary_raises():
    primary = RunnableLambda(lambda _: (_ for _ in ()).throw(RuntimeError("quota")))
    secondary = RunnableLambda(lambda _: AIMessage(content="from-groq"))
    # Bypass ChatModel requirements — exercise the compose helper via FallbackChatModel
    wrapper = FallbackChatModel.__new__(FallbackChatModel)
    wrapper._primary = MagicMock()
    wrapper._fallback = MagicMock()
    from src.llm import _with_fallbacks

    runnable = _with_fallbacks(primary, secondary)
    result = runnable.invoke("hi")
    assert result.content == "from-groq"


def test_fallback_not_used_when_primary_succeeds():
    primary = RunnableLambda(lambda _: AIMessage(content="from-openai"))
    secondary = RunnableLambda(lambda _: AIMessage(content="from-groq"))
    from src.llm import _with_fallbacks

    result = _with_fallbacks(primary, secondary).invoke("hi")
    assert result.content == "from-openai"


def test_with_structured_output_binds_both_providers():
    primary = MagicMock()
    fallback = MagicMock()
    primary_structured = RunnableLambda(lambda _: _DummySchema(answer="p"))
    fallback_structured = RunnableLambda(lambda _: _DummySchema(answer="f"))
    primary.with_structured_output.return_value = primary_structured
    fallback.with_structured_output.return_value = fallback_structured

    llm = FallbackChatModel(primary, fallback)
    chain = llm.with_structured_output(_DummySchema)

    primary.with_structured_output.assert_called_once_with(_DummySchema)
    fallback.with_structured_output.assert_called_once_with(_DummySchema)

    # Primary succeeds → no fallback
    assert chain.invoke("q").answer == "p"

    # Primary fails → fallback
    primary.with_structured_output.return_value = RunnableLambda(
        lambda _: (_ for _ in ()).throw(RuntimeError("quota"))
    )
    llm2 = FallbackChatModel(primary, fallback)
    # Re-bind with failing primary structured
    primary.with_structured_output.return_value = RunnableLambda(
        lambda _: (_ for _ in ()).throw(RuntimeError("quota"))
    )
    fallback.with_structured_output.return_value = fallback_structured
    chain2 = llm2.with_structured_output(_DummySchema)
    assert chain2.invoke("q").answer == "f"


def test_bind_tools_binds_both_providers():
    primary = MagicMock()
    fallback = MagicMock()
    primary.bind_tools.return_value = RunnableLambda(lambda _: AIMessage(content="p"))
    fallback.bind_tools.return_value = RunnableLambda(lambda _: AIMessage(content="f"))

    llm = FallbackChatModel(primary, fallback)
    tools = [MagicMock(name="tool")]
    bound = llm.bind_tools(tools)

    primary.bind_tools.assert_called_once_with(tools)
    fallback.bind_tools.assert_called_once_with(tools)
    assert bound.invoke("q").content == "p"


def test_lcel_pipe_works_with_fallback_wrapper():
    primary = MagicMock()
    fallback = MagicMock()
    with patch("src.llm._with_fallbacks") as mock_wf:
        mock_wf.return_value = RunnableLambda(
            lambda msgs: AIMessage(content="piped-ok")
        )
        llm = FallbackChatModel(primary, fallback)

    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.runnables import Runnable

    assert isinstance(llm, Runnable)

    prompt = ChatPromptTemplate.from_messages([("human", "{q}")])
    chain = prompt | llm | StrOutputParser()
    assert chain.invoke({"q": "hello"}) == "piped-ok"


@pytest.mark.parametrize(
    "method",
    ["invoke", "stream", "batch"],
)
def test_runnable_methods_delegate(method):
    primary = MagicMock()
    fallback = MagicMock()
    with patch("src.llm._with_fallbacks") as mock_wf:
        inner = MagicMock()
        mock_wf.return_value = inner
        llm = FallbackChatModel(primary, fallback)
        getattr(llm, method)("x")
        getattr(inner, method).assert_called()
