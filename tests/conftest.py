"""Pytest fixtures."""

from __future__ import annotations

import os


# Ensure tests never require real API keys or auth by default
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("REQUIRE_API_KEY", "false")
os.environ.setdefault("OPENAI_API_KEY", "test-key-for-pytest")
