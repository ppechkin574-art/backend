"""Custom 429 handler — Retry-After header + body fields.

slowapi's default `_rate_limit_exceeded_handler` returns
`{"error": "..."}` with NO Retry-After header. Mobile clients (Flutter
build 22) collapse this into a generic "Серверная ошибка" because they
can't distinguish 429 from 5xx. The custom handler fixes both surfaces:

1. Parses slowapi's `RateLimitExceeded.detail` (e.g. "1 per 1 minute")
   to extract the rate-limit *window* in seconds.
2. Returns `{"detail": "...", "retry_after_seconds": N}` body — same
   `detail` key as the rest of our error responses for client-parser
   consistency.
3. Adds `Retry-After: N` HTTP header — the RFC 7231 standard for
   rate-limit cool-down communication.

Covered:
- `_parse_retry_after_seconds` — all slowapi detail formats we use,
  plus malformed input fallback to 60s.
- `custom_rate_limit_exceeded_handler` — JSON body shape, status code,
  and the Retry-After header presence + value.
"""

from unittest.mock import MagicMock

import pytest
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request

from api.middlewares.rate_limit import (
    _parse_retry_after_seconds,
    custom_rate_limit_exceeded_handler,
)


# ─────────────────────────── _parse_retry_after_seconds ──────────────────


@pytest.mark.parametrize(
    "detail, expected_seconds",
    [
        # The two formats slowapi uses for our actual limits today.
        ("1 per 1 minute", 60),
        ("10 per hour", 3600),
        # Other plausible slowapi outputs we should handle gracefully.
        ("5 per 30 second", 30),
        ("100 per day", 86400),
        ("1 per minute", 60),  # no leading "1"
        ("3 per 5 minute", 300),
        # Edge cases
        ("RATE LIMIT EXCEEDED: 1 PER 1 MINUTE", 60),  # case-insensitive
    ],
)
def test_parse_retry_after_seconds_well_formed_inputs(detail, expected_seconds):
    assert _parse_retry_after_seconds(detail) == expected_seconds


def test_parse_retry_after_seconds_falls_back_on_garbage():
    """Defensive: an unparseable string returns 60s (matches the
    tightest limit we use anywhere — /auth/code/request 1/minute).
    Client always shows a usable countdown rather than crashing."""
    assert _parse_retry_after_seconds("garbage that doesn't match") == 60


def test_parse_retry_after_seconds_falls_back_on_empty():
    assert _parse_retry_after_seconds("") == 60


def test_parse_retry_after_seconds_falls_back_on_none():
    """slowapi sometimes constructs RateLimitExceeded without a detail
    string; we shouldn't crash on a None attribute."""
    assert _parse_retry_after_seconds(None) == 60


def test_parse_retry_after_seconds_unknown_unit_falls_back():
    """A future slowapi version using a unit we don't know about
    (e.g. 'week') falls back to 60s rather than computing 0."""
    assert _parse_retry_after_seconds("1 per 1 week") == 60


# ─────────────────────────── custom_rate_limit_exceeded_handler ──────────


def _fake_request(path: str = "/auth/code/request") -> Request:
    """Minimal Request mock — handler only reads method + url.path."""
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 0),
    }
    return Request(scope=scope)


@pytest.mark.asyncio
async def test_handler_returns_429_with_retry_after_header():
    """The headline contract: response is 429 and Retry-After is set."""
    exc = RateLimitExceeded(limit=MagicMock(error_message="1 per 1 minute"))
    exc.detail = "1 per 1 minute"  # slowapi attaches the string here
    request = _fake_request()

    response = await custom_rate_limit_exceeded_handler(request, exc)

    assert response.status_code == 429
    assert response.headers.get("Retry-After") == "60"


@pytest.mark.asyncio
async def test_handler_body_uses_detail_key_not_error_key():
    """Body uses `detail` (FastAPI convention) — matches our other
    error responses. Old slowapi default used `error`, breaking
    client-side error parsers that assume `detail`."""
    import json

    exc = RateLimitExceeded(limit=MagicMock(error_message="1 per 1 minute"))
    exc.detail = "1 per 1 minute"
    request = _fake_request()

    response = await custom_rate_limit_exceeded_handler(request, exc)
    body = json.loads(response.body.decode())

    assert "detail" in body
    assert "error" not in body  # explicitly NOT the old key
    assert "Rate limit exceeded" in body["detail"]


@pytest.mark.asyncio
async def test_handler_body_includes_retry_after_seconds():
    """Some Flutter dio configs strip headers from error responses,
    so the body must also carry the retry hint as a fallback."""
    import json

    exc = RateLimitExceeded(limit=MagicMock(error_message="10 per hour"))
    exc.detail = "10 per hour"
    request = _fake_request()

    response = await custom_rate_limit_exceeded_handler(request, exc)
    body = json.loads(response.body.decode())

    assert body.get("retry_after_seconds") == 3600
    # And the header carries the same value
    assert response.headers.get("Retry-After") == "3600"


@pytest.mark.asyncio
async def test_handler_handles_missing_detail_gracefully():
    """slowapi rarely produces an exception without a detail string —
    we should still return 429 with the fallback 60s, not crash."""
    exc = RateLimitExceeded(limit=MagicMock(error_message=""))
    exc.detail = ""  # empty
    request = _fake_request()

    response = await custom_rate_limit_exceeded_handler(request, exc)

    assert response.status_code == 429
    assert response.headers.get("Retry-After") == "60"


@pytest.mark.asyncio
async def test_handler_different_endpoints_get_correct_window():
    """Two endpoints with different limits → two different Retry-After
    values come back. Confirms the parser drives the header, not a
    constant."""
    import json

    # 1/minute endpoint
    exc1 = RateLimitExceeded(limit=MagicMock())
    exc1.detail = "1 per 1 minute"
    r1 = await custom_rate_limit_exceeded_handler(
        _fake_request("/auth/code/request"), exc1
    )
    assert r1.headers["Retry-After"] == "60"
    assert json.loads(r1.body)["retry_after_seconds"] == 60

    # 10/minute endpoint (e.g. /auth/code/check)
    exc2 = RateLimitExceeded(limit=MagicMock())
    exc2.detail = "10 per 1 minute"
    r2 = await custom_rate_limit_exceeded_handler(
        _fake_request("/auth/code/check"), exc2
    )
    assert r2.headers["Retry-After"] == "60"
    assert json.loads(r2.body)["retry_after_seconds"] == 60

    # 10/hour endpoint
    exc3 = RateLimitExceeded(limit=MagicMock())
    exc3.detail = "10 per hour"
    r3 = await custom_rate_limit_exceeded_handler(
        _fake_request("/auth/code/request"), exc3
    )
    assert r3.headers["Retry-After"] == "3600"
    assert json.loads(r3.body)["retry_after_seconds"] == 3600
