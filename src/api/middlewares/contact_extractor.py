"""Pre-parse the JSON body of /auth/code/request to expose the `contact`
field on request.state BEFORE slowapi's key_func runs.

Why this exists
---------------
slowapi's `@limiter.limit("10/hour")` decorator calls `key_func(request)`
during route dispatch — long before FastAPI parses the request body into
a Pydantic model. That makes contact-aware rate-limit decisions
("bypass this dev phone") impossible from inside key_func unless someone
has already read the body and stashed it somewhere.

This middleware does exactly that, and only for /auth/code/request:

  1. await request.body() — reads the raw bytes once, Starlette caches
     the result on request._body so downstream Pydantic parsing re-uses
     the cache instead of trying to consume an empty stream.
  2. JSON-parse + extract "contact" → request.state.contact
  3. Pass the request through unchanged.

Failure modes are intentionally silent: malformed JSON, missing field,
or non-JSON content-type just leave request.state.contact unset and the
key_func falls back to per-IP. Better to let the route's real validation
produce the canonical error than to short-circuit here.
"""

import json
import logging
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


# Only paths where we actually need contact-aware rate limiting. Adding
# more endpoints later is a one-line frozenset edit.
_TARGET_PATHS: frozenset[str] = frozenset({"/auth/code/request"})


class ContactExtractorMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method == "POST" and request.url.path in _TARGET_PATHS:
            try:
                body = await request.body()
                if body:
                    data = json.loads(body)
                    contact = data.get("contact") if isinstance(data, dict) else None
                    if isinstance(contact, str) and contact.strip():
                        request.state.contact = contact.strip()
            except (json.JSONDecodeError, UnicodeDecodeError):
                # Malformed body — route validation will reject it.
                pass
            except Exception as e:
                logger.warning(
                    "[contact-extractor] unexpected error reading body: %s", e
                )
        return await call_next(request)
