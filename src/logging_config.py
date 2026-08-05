"""Structured logging setup for production."""

from __future__ import annotations

import logging
import sys

from src.config import is_production


def setup_logging() -> None:
    """Configure application logging."""
    level = logging.INFO if is_production() else logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
        force=True,
    )
    if is_production():
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("chromadb").setLevel(logging.WARNING)
