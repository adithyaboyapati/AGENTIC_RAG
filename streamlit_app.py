"""
Agentic RAG Lab — Streamlit frontend.

Run from project root:
    streamlit run streamlit_app.py
"""

from __future__ import annotations

import logging
import uuid

# Bootstrap tracing BEFORE any LangChain imports
import src.bootstrap  # noqa: F401

import streamlit as st

from src.config import settings
from src.guardrails import RateLimitError
from src.logging_config import setup_logging
from src.memory.supabase_store import (
    clear_session,
    is_supabase_configured,
    load_messages,
    save_message,
)
from src.observability import get_tracing_status, init_langsmith_tracing
from src.runner import EXAMPLE_QUESTIONS, MODE_DESCRIPTIONS, MODE_LABELS, run_agent

setup_logging()
init_langsmith_tracing()

st.set_page_config(
    page_title="Agentic RAG Lab",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container { padding-top: 1.5rem; }
    .trace-step { font-size: 0.9rem; color: #555; margin-bottom: 0.25rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def init_session_state() -> None:
    if "session_id" not in st.session_state:
        # Full UUID — truncated IDs are guessable and collide across users
        st.session_state.session_id = uuid.uuid4().hex
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "memory_enabled" not in st.session_state:
        st.session_state.memory_enabled = settings.memory_enabled
    if "persist_supabase" not in st.session_state:
        st.session_state.persist_supabase = is_supabase_configured()


def render_trace(result) -> None:
    """Show agent decision trail in expandable panels."""
    if result.route:
        st.info(f"**Route:** `{result.route}` — {result.route_reason}")

    if result.grade_summary:
        st.warning(f"**Grader:** {result.grade_summary}")

    if result.decomposition_reason and result.mode == "decompose":
        st.markdown(f"**Decomposition:** {result.decomposition_reason}")
        if result.sub_queries:
            for i, q in enumerate(result.sub_queries, 1):
                st.markdown(f"{i}. {q}")

    if result.decomposition_reason and result.mode == "multi_hop":
        st.markdown(f"**Multi-hop plan:** {result.decomposition_reason}")
        if result.sub_queries:
            for i, q in enumerate(result.sub_queries, 1):
                st.markdown(f"**Hop {i}:** {q}")

    if result.steps:
        with st.expander("Agent steps", expanded=False):
            for step in result.steps:
                st.markdown(f"- {step}")

    if result.citations:
        with st.expander("Citations", expanded=False):
            for c in result.citations:
                page = f", p{c.page}" if c.page is not None else ""
                st.markdown(f"**[{c.index}]** `{c.source}{page}`")
                if c.snippet:
                    st.caption(c.snippet)
    elif result.sources:
        with st.expander("Sources", expanded=False):
            for src in result.sources:
                st.markdown(f"- `{src}`")


def render_follow_ups(follow_ups: list[str], key_prefix: str) -> None:
    """Clickable follow-up suggestions that queue the next question."""
    if not follow_ups:
        return
    st.markdown("**Suggested follow-ups**")
    for i, q in enumerate(follow_ups):
        if st.button(q, key=f"{key_prefix}-fu-{i}", use_container_width=True):
            st.session_state.pending_question = q
            st.rerun()


def persist_exchange(session_id: str, question: str, answer: str, mode: str) -> None:
    """Save user/assistant turn to Supabase if persistence is enabled."""
    if not st.session_state.persist_supabase or not is_supabase_configured():
        return
    save_message(session_id, "user", question, mode)
    save_message(session_id, "assistant", answer, mode)


def main() -> None:
    init_session_state()

    with st.sidebar:
        st.title("Agentic RAG Lab")
        st.caption("Project-based learning — Phases 1–7")

        mode = st.selectbox(
            "Agent mode",
            options=list(MODE_LABELS.keys()),
            format_func=lambda k: MODE_LABELS[k],
        )
        st.markdown(f"_{MODE_DESCRIPTIONS[mode]}_")

        show_trace = st.toggle("Show agent trace", value=True)

        st.divider()
        st.subheader("Memory")
        st.session_state.memory_enabled = st.toggle(
            "Enable conversation memory",
            value=st.session_state.memory_enabled,
            help="Agent sees prior messages for follow-up questions",
        )

        if is_supabase_configured():
            st.session_state.persist_supabase = st.toggle(
                "Persist to Supabase",
                value=st.session_state.persist_supabase,
                help="Save chat history across browser sessions",
            )
            st.caption(f"Session: `{st.session_state.session_id}`")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("New session", use_container_width=True):
                    st.session_state.session_id = uuid.uuid4().hex
                    st.session_state.messages = []
                    st.rerun()
            with col2:
                if st.button("Load session", use_container_width=True):
                    loaded = load_messages(st.session_state.session_id)
                    st.session_state.messages = [
                        {"role": m["role"], "content": m["content"]} for m in loaded
                    ]
                    st.rerun()
        else:
            st.caption("In-session memory only")
            st.info("Add SUPABASE_URL + SUPABASE_KEY to .env for persistent memory")

        st.divider()
        st.subheader("LangSmith")
        trace_status = get_tracing_status()
        if trace_status["active"] == "True":
            st.success(f"Tracing ON → `{trace_status['project']}`")
            st.caption("[View traces](https://smith.langchain.com)")
        elif trace_status["configured"] == "True":
            st.warning("Tracing configured but not active — restart Streamlit")
        else:
            st.error("Tracing OFF — set LANGSMITH_TRACING=true in .env")

        st.divider()
        st.subheader("Example question")
        if st.button("Load example", use_container_width=True):
            st.session_state.pending_question = EXAMPLE_QUESTIONS[mode]

        st.divider()
        st.subheader("Corpus")
        st.markdown(
            "Knowledge base: **RAG Survey** (`rag.pdf`)\n\n"
            "Re-ingest: `python -m src.ingestion.ingest --source data/sample_docs`"
        )

        if st.button("Clear chat", use_container_width=True):
            if st.session_state.persist_supabase and is_supabase_configured():
                clear_session(st.session_state.session_id)
            st.session_state.messages = []
            st.rerun()

    st.title("Research Assistant")
    caption = f"Active mode: **{MODE_LABELS[mode]}**"
    if st.session_state.memory_enabled:
        caption += f" | Memory: **ON** ({len(st.session_state.messages)} messages)"
    st.caption(caption)

    for idx, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant" and msg.get("trace") and show_trace:
                render_trace(msg["trace"])
            if msg["role"] == "assistant" and msg.get("follow_ups"):
                render_follow_ups(msg["follow_ups"], key_prefix=f"hist-{idx}")

    question = st.chat_input("Ask a question about RAG…")

    if not question and st.session_state.get("pending_question"):
        question = st.session_state.pop("pending_question")

    if question:
        history = list(st.session_state.messages) if st.session_state.memory_enabled else None

        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner(f"Running {MODE_LABELS[mode]}…"):
                try:
                    result = run_agent(
                        question,
                        mode,
                        chat_history=history,
                        use_memory=st.session_state.memory_enabled,
                    )
                    st.markdown(result.answer)
                    if show_trace:
                        render_trace(result)
                    render_follow_ups(result.follow_ups, key_prefix="live")
                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": result.answer,
                            "trace": result,
                            "follow_ups": result.follow_ups,
                        }
                    )
                    persist_exchange(
                        st.session_state.session_id,
                        question,
                        result.answer,
                        mode,
                    )
                except (ValueError, RateLimitError) as exc:
                    # Guardrail rejections carry user-actionable messages
                    st.warning(str(exc))
                    st.session_state.messages.append(
                        {"role": "assistant", "content": str(exc), "trace": None}
                    )
                except Exception:
                    logging.getLogger(__name__).exception("Agent run failed")
                    message = "Something went wrong while processing your question. Please try again."
                    st.error(message)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": message, "trace": None}
                    )


if __name__ == "__main__":
    main()
