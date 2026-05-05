"""Verify _real_client_ip falls through proxy headers correctly.

If this regression-tests, slowapi will accidentally rate-limit per-Railway-
proxy-IP again instead of per-actual-client.
"""

from unittest.mock import MagicMock

from api.middlewares.rate_limit import _real_client_ip


def _request(headers: dict | None = None, client_host: str | None = None) -> MagicMock:
    req = MagicMock()
    req.headers = headers or {}
    if client_host:
        req.client = MagicMock()
        req.client.host = client_host
    else:
        req.client = None
    return req


def test_uses_x_forwarded_for_first_hop():
    req = _request(
        headers={"x-forwarded-for": "203.0.113.42, 10.0.0.1, 10.0.0.2"},
        client_host="10.0.0.99",
    )
    assert _real_client_ip(req) == "203.0.113.42"


def test_uses_x_real_ip_when_xff_absent():
    req = _request(
        headers={"x-real-ip": "203.0.113.99"},
        client_host="10.0.0.99",
    )
    assert _real_client_ip(req) == "203.0.113.99"


def test_falls_back_to_request_client_host_when_no_proxy_headers():
    req = _request(headers={}, client_host="127.0.0.1")
    assert _real_client_ip(req) == "127.0.0.1"


def test_returns_loopback_when_request_has_no_client():
    req = _request(headers={}, client_host=None)
    assert _real_client_ip(req) == "127.0.0.1"


def test_xff_takes_precedence_over_real_ip():
    """When both are set (some misconfigured proxies do this), XFF wins
    because it's the standard and documents the full chain."""
    req = _request(
        headers={"x-forwarded-for": "203.0.113.42", "x-real-ip": "9.9.9.9"},
        client_host="10.0.0.99",
    )
    assert _real_client_ip(req) == "203.0.113.42"
