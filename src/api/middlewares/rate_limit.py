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

from slowapi import Limiter
from starlette.requests import Request

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
