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
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)


def _build_limiter() -> Limiter:
    storage_uri = os.getenv("RATELIMIT_STORAGE_URI") or os.getenv("REDIS_URL")
    kwargs: dict = {"key_func": get_remote_address}
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
