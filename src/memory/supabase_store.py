"""Supabase-backed persistent chat memory."""

from __future__ import annotations

import logging
from typing import Any

from src.config import settings

logger = logging.getLogger(__name__)

_client: Any | None = None
_client_initialized = False


def is_supabase_configured() -> bool:
    return bool(settings.supabase_url and settings.supabase_key)


def get_supabase_client():
    """Return cached Supabase client or None if not configured."""
    global _client, _client_initialized

    if _client_initialized:
        return _client

    _client_initialized = True

    if not is_supabase_configured():
        logger.debug("Supabase not configured — using in-session memory only")
        return None

    try:
        from supabase import create_client

        _client = create_client(settings.supabase_url, settings.supabase_key)
        logger.info("Supabase memory store connected")
    except Exception as exc:
        logger.warning("Failed to connect to Supabase: %s", exc)
        _client = None

    return _client


def save_message(session_id: str, role: str, content: str, mode: str = "") -> bool:
    """Persist a single chat message."""
    client = get_supabase_client()
    if client is None:
        return False

    try:
        client.table(settings.supabase_chat_table).insert(
            {
                "session_id": session_id,
                "role": role,
                "content": content,
                "mode": mode,
            }
        ).execute()
        return True
    except Exception as exc:
        logger.warning("Failed to save message to Supabase: %s", exc)
        return False


def load_messages(session_id: str, limit: int = 50) -> list[dict[str, str]]:
    """Load chat history for a session from Supabase."""
    client = get_supabase_client()
    if client is None:
        return []

    try:
        response = (
            client.table(settings.supabase_chat_table)
            .select("role, content, mode, created_at")
            .eq("session_id", session_id)
            .order("created_at")
            .limit(limit)
            .execute()
        )
        return [
            {"role": row["role"], "content": row["content"], "mode": row.get("mode", "")}
            for row in response.data or []
        ]
    except Exception as exc:
        logger.warning("Failed to load messages from Supabase: %s", exc)
        return []


def clear_session(session_id: str) -> bool:
    """Delete all messages for a session."""
    client = get_supabase_client()
    if client is None:
        return False

    try:
        client.table(settings.supabase_chat_table).delete().eq("session_id", session_id).execute()
        return True
    except Exception as exc:
        logger.warning("Failed to clear Supabase session: %s", exc)
        return False


def list_sessions(limit: int = 20) -> list[dict[str, str]]:
    """List recent chat sessions (distinct session_ids)."""
    client = get_supabase_client()
    if client is None:
        return []

    try:
        response = (
            client.table(settings.supabase_chat_table)
            .select("session_id, created_at")
            .order("created_at", desc=True)
            .limit(limit * 5)
            .execute()
        )
        seen: set[str] = set()
        sessions: list[dict[str, str]] = []
        for row in response.data or []:
            sid = row["session_id"]
            if sid not in seen:
                seen.add(sid)
                sessions.append({"session_id": sid, "created_at": row.get("created_at", "")})
            if len(sessions) >= limit:
                break
        return sessions
    except Exception as exc:
        logger.warning("Failed to list Supabase sessions: %s", exc)
        return []
