"""Resolve request locale from the `Accept-Language` header and expose
it on `request.state.locale` for downstream services / DTOs.

Why this exists
---------------
Phase 7b ships Kazakh translations of the question bank.  The Flutter
client signals language preference via the standard `Accept-Language`
header (`kk` or `ru`).  Services that build question/hint DTOs need to
know that preference to decide whether to read the `_kk` cache column
or fall back to the Russian `text_blocks` rendering.

Header parsing rules (intentionally narrow for the pilot)
---------------------------------------------------------
1.  Header missing or empty  → `"ru"` (production default).
2.  Header starts with `kk`  → `"kk"` (RFC 5646 — primary subtag wins;
    `kk`, `kk-KZ`, `kk-Cyrl-KZ` all resolve the same).
3.  Header starts with `ru`  → `"ru"`.
4.  Anything else            → `"ru"` (defensive default, e.g. a stray
    `en` from a desktop browser shouldn't 500 the question endpoint).

We deliberately do NOT parse the full quality-value (`q=`) negotiation
table.  The mobile app sends exactly one tag; over-engineering this
would just add a regex maintenance burden.  If the web client ever
needs richer negotiation we can swap in `Babel.negotiate_locale`.
"""

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


_SUPPORTED: frozenset[str] = frozenset({"ru", "kk"})
_DEFAULT_LOCALE: str = "ru"


def resolve_locale(accept_language: str | None) -> str:
    """Pure function — exposed for unit testing without spinning up
    the full ASGI app.  Returns one of `{"ru", "kk"}`.
    """
    if not accept_language:
        return _DEFAULT_LOCALE

    # Take the first comma-separated tag, strip whitespace + q-value
    first = accept_language.split(",", 1)[0].strip().lower()
    if ";" in first:
        first = first.split(";", 1)[0].strip()
    # Primary subtag: "kk-KZ" → "kk"
    primary = first.split("-", 1)[0]

    return primary if primary in _SUPPORTED else _DEFAULT_LOCALE


class LocaleMiddleware(BaseHTTPMiddleware):
    """Populate `request.state.locale` with `"ru"` or `"kk"` based on
    the `Accept-Language` header.  Always sets a value — downstream
    code can rely on the attribute existing.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.locale = resolve_locale(request.headers.get("accept-language"))
        return await call_next(request)


def get_locale(request: Request) -> str:
    """FastAPI `Depends()` accessor for the resolved request locale.

    Returns whatever `LocaleMiddleware` stamped on `request.state.locale`,
    or the default `"ru"` if the middleware didn't run for some reason
    (e.g. a route bypassed via TestClient that mounts the router without
    the full ASGI app).  Endpoints can write `locale: str = Depends(get_locale)`
    and pass the value through to services without reaching for `request`
    themselves — keeps services testable without an ASGI fixture.
    """
    return getattr(request.state, "locale", _DEFAULT_LOCALE)
