"""Tests for outbound URL / SSRF protection."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.security.ssrf import OutboundUrlPolicy, UnsafeOutboundUrl, validate_outbound_url, validate_webhook_url


def test_validate_outbound_url_blocks_loopback():
    with pytest.raises(UnsafeOutboundUrl):
        validate_outbound_url("http://127.0.0.1/hook")


def test_validate_outbound_url_blocks_metadata_ip():
    with pytest.raises(UnsafeOutboundUrl):
        validate_outbound_url("http://169.254.169.254/latest/meta-data")


def test_validate_outbound_url_blocks_private_ranges():
    for url in (
        "http://10.0.0.1",
        "http://172.16.0.1",
        "http://192.168.0.1",
    ):
        with pytest.raises(UnsafeOutboundUrl):
            validate_outbound_url(url)


def test_validate_outbound_url_blocks_invalid_schemes():
    with pytest.raises(UnsafeOutboundUrl):
        validate_outbound_url("file:///etc/passwd")
    with pytest.raises(UnsafeOutboundUrl):
        validate_outbound_url("ftp://example.com")


def test_validate_outbound_url_allows_public_https_without_dns():
    policy = OutboundUrlPolicy(resolve_dns=False)
    assert validate_outbound_url("https://example.com", policy=policy) == "https://example.com"


def test_validate_webhook_url_still_blocks_private():
    with pytest.raises(UnsafeOutboundUrl):
        validate_webhook_url("http://127.0.0.1/hook")


def test_dns_rebinding_resistance_blocks_resolved_private_ip():
    policy = OutboundUrlPolicy(resolve_dns=True)

    def fake_getaddrinfo(host, port, type=None):
        return [(None, None, None, None, ("10.0.0.5", port or 443))]

    with patch("src.security.ssrf.socket.getaddrinfo", fake_getaddrinfo):
        with pytest.raises(UnsafeOutboundUrl, match="resolves"):
            validate_outbound_url("https://safe-looking.example", policy=policy)
