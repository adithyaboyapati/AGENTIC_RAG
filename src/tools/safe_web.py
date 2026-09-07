"""Canonical web-search egress helpers."""

from __future__ import annotations

import logging
import re

from src.security.ssrf import OutboundUrlPolicy, UnsafeOutboundUrl, validate_outbound_url

logger = logging.getLogger(__name__)

_URL_IN_TEXT_RE = re.compile(r"https?://[^\s\])\"'<>]+", re.IGNORECASE)


def extract_urls(text: str) -> list[str]:
    return _URL_IN_TEXT_RE.findall(text or "")


def filter_safe_urls(
    urls: list[str],
    *,
    policy: OutboundUrlPolicy | None = None,
) -> tuple[list[str], list[str]]:
    """Return (allowed_urls, blocked_urls) after SSRF validation."""
    allowed: list[str] = []
    blocked: list[str] = []
    for raw in urls:
        try:
            safe = validate_outbound_url(raw, policy=policy)
            if safe:
                allowed.append(safe)
        except UnsafeOutboundUrl:
            blocked.append(raw)
            logger.warning("Blocked unsafe web-search URL: %s", raw[:120])
    return allowed, blocked


def validate_web_search_egress(text: str) -> list[str]:
    """Validate any URLs embedded in web-search result text."""
    _, blocked = filter_safe_urls(extract_urls(text))
    return blocked
