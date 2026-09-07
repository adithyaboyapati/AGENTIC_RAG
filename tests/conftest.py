"""Pytest fixtures."""

from __future__ import annotations

import os
from pathlib import Path

# Force isolation — setdefault would inherit a developer's real .env via
# pydantic-settings env_file, including LangSmith keys.
os.environ["ENVIRONMENT"] = "development"
os.environ["REQUIRE_API_KEY"] = "false"
os.environ["OPENAI_API_KEY"] = "test-key-for-pytest"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGSMITH_TRACING_V2"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_API_KEY"] = ""
os.environ["LANGCHAIN_API_KEY"] = ""
os.environ["RATE_LIMIT_BACKEND"] = "memory"
os.environ["CACHE_ENABLED"] = "false"

# Keep the demo SQLite catalog out of git (data/sources/*.db is ignored)
_kb_dir = Path(__file__).resolve().parent.parent / "data" / "sources"
_kb_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("KNOWLEDGE_DB_PATH", str(_kb_dir / "pytest-knowledge.db"))
