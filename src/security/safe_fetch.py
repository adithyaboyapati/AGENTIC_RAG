"""Safe outbound HTTP fetch with SSRF protection."""

from __future__ import annotations

import urllib.request
from typing import Any

from src.security.ssrf import OutboundUrlPolicy, UnsafeOutboundUrl, validate_outbound_url


def safe_urlopen(
    url: str,
    *,
    timeout: float = 10.0,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    policy: OutboundUrlPolicy | None = None,
) -> Any:
    """Open a URL only after deterministic SSRF validation."""
    safe = validate_outbound_url(url, policy=policy)
    if not safe:
        raise UnsafeOutboundUrl("empty or invalid URL")
    req = urllib.request.Request(
        safe,
        data=data,
        headers=headers or {},
        method=method,
    )
    return urllib.request.urlopen(req, timeout=timeout)
