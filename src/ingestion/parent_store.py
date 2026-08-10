"""Sidecar store for parent section documents (section-aware parent–child RAG)."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from langchain_core.documents import Document

from src.config import PROJECT_ROOT, settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cache: dict[str, dict] | None = None


def parent_store_path() -> Path:
    path = Path(settings.parent_store_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _load() -> dict[str, dict]:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        path = parent_store_path()
        if not path.exists():
            _cache = {}
            return _cache
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
        _cache = data
        return _cache


def save_parents(parents: list[Document], *, merge: bool = True) -> None:
    """Persist parent sections keyed by parent_id."""
    global _cache
    path = parent_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, dict] = _load().copy() if merge else {}
    for parent in parents:
        parent_id = str(parent.metadata.get("parent_id") or "")
        if not parent_id:
            continue
        payload[parent_id] = {
            "page_content": parent.page_content,
            "metadata": dict(parent.metadata),
        }

    with _lock:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        _cache = payload
    logger.info("Saved %d parent sections → %s", len(payload), path)


def clear_parents() -> None:
    global _cache
    path = parent_store_path()
    with _lock:
        if path.exists():
            path.unlink()
        _cache = {}


def get_parent(parent_id: str) -> Document | None:
    if not parent_id:
        return None
    data = _load().get(parent_id)
    if not data:
        return None
    return Document(
        page_content=data.get("page_content", ""),
        metadata=dict(data.get("metadata") or {}),
    )


def expand_children_to_parents(
    children: list[Document],
    *,
    max_parent_chars: int | None = None,
) -> list[Document]:
    """
    Deduplicate by parent_id and return parent Documents for generation.

    Falls back to the child itself when no parent is stored (fixed chunking).
    """
    limit = (
        max_parent_chars
        if max_parent_chars is not None
        else settings.parent_max_chars
    )
    seen: set[str] = set()
    expanded: list[Document] = []

    for child in children:
        parent_id = str(child.metadata.get("parent_id") or "")
        if parent_id and parent_id in seen:
            continue

        parent = get_parent(parent_id) if parent_id else None
        if parent is None:
            # Already a leaf / fixed chunk — keep child once
            key = parent_id or str(child.metadata.get("chunk_id") or id(child))
            if key in seen:
                continue
            seen.add(key)
            expanded.append(child)
            continue

        seen.add(parent_id)
        text = parent.page_content
        if limit and len(text) > limit:
            text = text[:limit].rstrip() + "\n…"

        section_path = parent.metadata.get("section_path") or parent.metadata.get(
            "section_title", ""
        )
        # Keep child score/chunk_id for citation provenance
        meta = {
            **dict(parent.metadata),
            "doc_type": "parent",
            "chunk_id": child.metadata.get("chunk_id") or parent_id,
            "matched_child_id": child.metadata.get("chunk_id"),
            "score": child.metadata.get("score"),
            "rerank_score": child.metadata.get("rerank_score"),
            "retrieval_score": child.metadata.get("retrieval_score"),
            "expanded_from_child": True,
        }
        content = text
        if section_path and not content.startswith("Section:"):
            content = f"Section: {section_path}\n\n{text}"
        expanded.append(Document(page_content=content, metadata=meta))

    return expanded


def invalidate_cache() -> None:
    global _cache
    with _lock:
        _cache = None
