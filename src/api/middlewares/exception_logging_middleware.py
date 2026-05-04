import logging
import traceback
from collections.abc import Awaitable, Callable

from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from api.exceptions.documentation import EXCEPTION_DOCS
from clients import NotificationClientInterface, NotificationMessageDTO
from clients.notification import CodePlatform

logger = logging.getLogger(__name__)


class ExceptionLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]],
        notifier: NotificationClientInterface,
        notifier_receiver_phone: str,
        **kwargs,
    ):
        super().__init__(
            app,
            **kwargs,
        )
        self._notifier = notifier
        self._notifier_receiver_phone = notifier_receiver_phone

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        try:
            return await call_next(request)
        except RateLimitExceeded as exc:
            logger.warning(
                "[rate-limit] %s %s — limit=%s",
                request.method,
                request.url.path,
                getattr(exc, "detail", str(exc)),
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"Rate limit exceeded: {getattr(exc, 'detail', str(exc))}",
                },
                headers={"Retry-After": "60"},
            )
        except Exception as e:
            status_code = next(
                (doc["status_code"] for exc_type, doc in EXCEPTION_DOCS.items() if isinstance(e, exc_type)),
                500,
            )

            if status_code == 500:
                logger.exception(
                    "500 Internal Server Error: %s %s\nException: %s: %s\nFull traceback:\n%s",
                    request.method,
                    request.url.path,
                    e.__class__.__name__,
                    str(e),
                    traceback.format_exc(),
                )

                try:
                    message = NotificationMessageDTO(
                        to=self._notifier_receiver_phone,
                        message=f"<b>🚨 Exception</b> in <code>{request.url.path}</code>\n"
                        f"<pre>{e.__class__.__module__}.{e.__class__.__name__}: {str(e)}</pre>",
                        platform=CodePlatform.TELEGRAM,
                    )
                    self._notifier.notify(message)
                except Exception as tg_e:
                    logger.warning("Failed to notify via Telegram: %s", tg_e)
            else:
                logger.warning(
                    "%s Error: %s %s - %s: %s",
                    status_code,
                    request.method,
                    request.url.path,
                    e.__class__.__name__,
                    str(e),
                )

            if str(e):
                detail = str(e)
            else:
                detail = next(
                    (doc["description"] for exc_type, doc in EXCEPTION_DOCS.items() if isinstance(e, exc_type)),
                    "Noname Error",
                )

            return JSONResponse(
                status_code=status_code,
                content={"detail": detail},
            )
