"""Pytest fixtures."""

from __future__ import annotations

import os
from pathlib import Path

# Ensure tests never require real API keys or auth by default
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("REQUIRE_API_KEY", "false")
os.environ.setdefault("OPENAI_API_KEY", "test-key-for-pytest")

# Keep the demo SQLite catalog out of git (data/sources/*.db is ignored)
_kb_dir = Path(__file__).resolve().parent.parent / "data" / "sources"
_kb_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("KNOWLEDGE_DB_PATH", str(_kb_dir / "pytest-knowledge.db"))
