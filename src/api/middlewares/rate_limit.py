"""Rate limiting via slowapi.

Default backend: in-process memory. With Redis-backed storage, multiple Railway
replicas would share the same counters — set RATELIMIT_STORAGE_URI to the
project Redis URL.

Usage:
    from api.middlewares.rate_limit import limiter

    @router.post("/code/request")
    @limiter.limit("1/minute")
    async def request_code(request: Request, ...):
        ...

The endpoint MUST accept `request: Request` (or `response: Response`) as a
parameter — slowapi reads it from the function signature to derive the
client IP.
"""

import logging
import os
import re

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


def _real_client_ip(request: Request) -> str:
    """Return the real client IP, taking Railway's proxy headers into account.

    slowapi.util.get_remote_address uses request.client.host which on Railway
    is the IP of one of their edge proxies. The pool rotates → each request
    can come from a different host, breaking per-IP counters. We honour
    X-Forwarded-For (first hop is the original client) and X-Real-IP as a
    fallback. If neither is present (local dev), fall back to client.host.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    xri = request.headers.get("x-real-ip")
    if xri:
        return xri.strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


def _build_limiter() -> Limiter:
    storage_uri = os.getenv("RATELIMIT_STORAGE_URI") or os.getenv("REDIS_URL")
    kwargs: dict = {"key_func": _real_client_ip}
    if storage_uri:
        kwargs["storage_uri"] = storage_uri
    return Limiter(**kwargs)


def log_storage_choice() -> None:
    """Logged from create_app() AFTER setup_logging, otherwise message is lost."""
    storage_uri = os.getenv("RATELIMIT_STORAGE_URI") or os.getenv("REDIS_URL")
    if storage_uri:
        host = storage_uri.split("@")[-1]
        logger.info("[rate-limit] storage backend: redis @ %s", host)
    else:
        logger.warning("[rate-limit] storage backend: in-memory (NOT cluster-safe)")


limiter = _build_limiter()


# ─────────────────────────── 429 handler with Retry-After ──────────────────


_UNIT_TO_SECONDS = {
    "second": 1,
    "minute": 60,
    "hour": 3600,
    "day": 86400,
}

# slowapi formats RateLimitExceeded.detail as "X per [N] unit" — e.g.
# "1 per 1 minute", "10 per hour", "5 per 30 second". We parse the window
# to set Retry-After. Falls back to 60s on parse failure (matches the
# tightest limit we use anywhere — /auth/code/request).
_DETAIL_RE = re.compile(r"per\s+(\d+)?\s*(second|minute|hour|day)", re.IGNORECASE)


def _parse_retry_after_seconds(detail: str | None) -> int:
    """Best-effort parse of slowapi's rate-limit message to extract the
    window in seconds. Used to set the `Retry-After` HTTP header so
    clients can build accurate countdown UIs without hardcoding limits.

    Examples:
        "1 per 1 minute" → 60
        "10 per hour"    → 3600
        "5 per 30 second" → 30
        "garbage"        → 60 (safe default)

    Returns the FULL window, not remaining seconds — we don't know how
    much of the window has already elapsed without querying slowapi's
    storage, which would add complexity for marginal benefit (clients
    showing a slightly-too-long countdown is benign UX).
    """
    if not detail:
        return 60
    match = _DETAIL_RE.search(detail)
    if not match:
        return 60
    count = int(match.group(1) or 1)
    unit = match.group(2).lower()
    return count * _UNIT_TO_SECONDS.get(unit, 60)


async def custom_rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """Replacement for slowapi's default `_rate_limit_exceeded_handler`.

    Adds two pieces of information the default handler omits:

    1. **`Retry-After` HTTP header** (RFC 7231) — the standard way for
       servers to tell clients when to retry. Mobile/web clients with
       generic HTTP interceptors can wire countdown UIs off this header
       without app-specific parsing.
    2. **`retry_after_seconds` in the body** — for clients that don't
       have header access (e.g. some Flutter `dio` configurations
       strip headers in error paths).

    Body shape also normalised to `{"detail": "..."}` matching the rest
    of our error responses (FastAPI HTTPException, validation errors).
    The old `{"error": "..."}` shape from slowapi's default broke pattern
    consistency on the client side.
    """
    detail = str(getattr(exc, "detail", "") or "")
    retry_after = _parse_retry_after_seconds(detail)
    logger.warning(
        "[rate-limit] %s %s — %s (retry_after=%ss)",
        request.method,
        request.url.path,
        detail,
        retry_after,
    )
    return JSONResponse(
        status_code=429,
        content={
            "detail": f"Rate limit exceeded: {detail}",
            "retry_after_seconds": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )
