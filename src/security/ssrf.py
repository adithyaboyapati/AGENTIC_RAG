"""Outbound URL validation — block SSRF to internal networks."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from src.config import is_production, settings

_BLOCKED_HOSTS = frozenset(
    {
        "metadata.google.internal",
        "metadata.google.com",
        "169.254.169.254",
        "metadata",
        "localhost",
    }
)

_LOCALHOST_ALIASES = frozenset({"localhost", "localhost.localdomain"})


class UnsafeOutboundUrl(ValueError):
    """Raised when an outbound URL is not allowed to be fetched by this process."""


class UnsafeWebhookUrl(UnsafeOutboundUrl):
    """Backward-compatible alias for webhook validation failures."""


@dataclass(frozen=True)
class OutboundUrlPolicy:
    """Policy knobs for ``validate_outbound_url``."""

    allowed_schemes: frozenset[str] = frozenset({"http", "https"})
    require_https_in_production: bool = True
    blocked_ports: frozenset[int] = frozenset({22, 25, 3306, 5432, 6379, 27017, 11211})
    hostname_allowlist: frozenset[str] | None = None
    allow_credentials: bool = False
    resolve_dns: bool = True


def _hostname_allowed(hostname: str, allowlist: frozenset[str] | None) -> bool:
    if allowlist is None:
        return True
    if not allowlist:
        return True
    return hostname.lower() in allowlist


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolve_host_ips(hostname: str, port: int | None) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve hostname and return parsed IP addresses (DNS rebinding resistant)."""
    try:
        infos = socket.getaddrinfo(hostname, port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeOutboundUrl(
            f"hostname could not be resolved: {hostname}"
        ) from exc

    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        try:
            ips.append(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            continue
    if not ips:
        raise UnsafeOutboundUrl(f"hostname resolved to no usable addresses: {hostname}")
    return ips


def validate_outbound_url(
    url: str | None,
    *,
    policy: OutboundUrlPolicy | None = None,
) -> str | None:
    """Return a sanitized URL or None if empty. Raise UnsafeOutboundUrl otherwise.

    Performs deterministic checks only — never uses an LLM to judge safety.
    When ``resolve_dns`` is enabled, resolved IP addresses are checked so the
    decision is not based on hostname alone.
    """
    if url is None:
        return None
    candidate = url.strip()
    if not candidate:
        return None

    pol = policy or OutboundUrlPolicy()
    parsed = urlparse(candidate)

    if parsed.scheme not in pol.allowed_schemes:
        raise UnsafeOutboundUrl(
            f"URL scheme {parsed.scheme!r} is not allowed "
            f"(allowed: {sorted(pol.allowed_schemes)})"
        )
    if pol.require_https_in_production and is_production() and parsed.scheme != "https":
        raise UnsafeOutboundUrl("https is required for outbound URLs in production")
    if not pol.allow_credentials and (parsed.username or parsed.password):
        raise UnsafeOutboundUrl("URL must not include credentials")
    if parsed.port in pol.blocked_ports:
        raise UnsafeOutboundUrl("URL uses a blocked port")

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise UnsafeOutboundUrl("URL is missing a hostname")
    if hostname in _BLOCKED_HOSTS or hostname in _LOCALHOST_ALIASES:
        raise UnsafeOutboundUrl("URL hostname is blocked")

    allowlist = pol.hostname_allowlist
    if allowlist is None and (settings.webhook_allowed_hosts or "").strip():
        allowlist = frozenset(
            h.strip().lower()
            for h in settings.webhook_allowed_hosts.split(",")
            if h.strip()
        )
    if not _hostname_allowed(hostname, allowlist):
        raise UnsafeOutboundUrl(
            "URL hostname is not in the allowed host list (WEBHOOK_ALLOWED_HOSTS)"
        )

    # Literal IP in URL — validate directly (do not trust hostname string alone).
    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None
    if literal_ip is not None and _is_blocked_ip(literal_ip):
        raise UnsafeOutboundUrl("URL targets a private or reserved address")

    if pol.resolve_dns:
        for ip in _resolve_host_ips(hostname, parsed.port):
            if _is_blocked_ip(ip):
                raise UnsafeOutboundUrl(
                    "URL resolves to a private, loopback, link-local, or reserved address"
                )

    return candidate


def validate_webhook_url(url: str | None) -> str | None:
    """Webhook-specific wrapper around ``validate_outbound_url``."""
    if url is None:
        return None
    candidate = url.strip()
    if not candidate:
        return None

    if is_production() and not (settings.webhook_secret or "").strip():
        raise UnsafeWebhookUrl(
            "WEBHOOK_SECRET must be set before webhook_url can be used in production"
        )

    allowlist: frozenset[str] | None = None
    raw = (settings.webhook_allowed_hosts or "").strip()
    if raw:
        allowlist = frozenset(h.strip().lower() for h in raw.split(",") if h.strip())

    try:
        return validate_outbound_url(
            candidate,
            policy=OutboundUrlPolicy(
                allowed_schemes=frozenset({"http", "https"}),
                require_https_in_production=True,
                hostname_allowlist=allowlist,
                allow_credentials=False,
                resolve_dns=True,
            ),
        )
    except UnsafeOutboundUrl as exc:
        raise UnsafeWebhookUrl(str(exc)) from exc
