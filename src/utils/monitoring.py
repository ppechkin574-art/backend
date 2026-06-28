import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request, Response
from prometheus_client import Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

ALMATY_TZ = ZoneInfo("Asia/Almaty")

REQUEST_COUNT = Counter(
    "aimaapp_requests_total",
    "Total requests",
    ["method", "endpoint", "status_code"],
)

REQUEST_DURATION = Histogram(
    "aimaapp_request_duration_seconds",
    "Request duration",
    ["method", "endpoint"],
)

ERROR_COUNT = Counter(
    "aimaapp_errors_total",
    "Total errors",
    ["method", "endpoint", "error_type"],
)

# Payment / subscription observability. `platform` = apple|google,
# `result` = active|inactive|rejected|error (verify) or the S2S event type.
IAP_VERIFY_COUNT = Counter(
    "aimaapp_iap_verify_total",
    "In-app purchase receipt verifications",
    ["platform", "result"],
)

IAP_EVENT_COUNT = Counter(
    "aimaapp_iap_event_total",
    "Subscription lifecycle events (purchase/renew/expire/refund/revoke)",
    ["platform", "event"],
)

LEVEL_MAP = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(ALMATY_TZ).strftime("%d.%m.%Y %H:%M:%S"),
            "level": record.levelname,
            "level_no": LEVEL_MAP.get(record.levelname, 0),
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if hasattr(record, "props"):
            log_entry.update(record.props)

        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": (self.formatException(record.exc_info) if record.exc_info else None),
            }

        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    json_formatter = JsonFormatter()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(json_formatter)
    logger.addHandler(stream_handler)

    logging.getLogger("api").setLevel(logging.INFO)
    logging.getLogger("quiz").setLevel(logging.INFO)
    logging.getLogger("auth").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


class LoggingContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        skip_paths = ["/metrics", "/health", "/ready", "/docs", "/openapi.json"]
        if request.url.path in skip_paths:
            return await call_next(request)

        request_id = str(uuid.uuid4())
        client_ip = get_client_ip(request)

        user_data = {
            "user_id": "anonymous",
            "username": None,
        }
        auth_header = request.headers.get("authorization")

        if auth_header and auth_header.startswith("Bearer "):
            try:
                auth_service = request.app.state.container.auth_service()
                user_dto = auth_service.get_user_from_token(auth_header.replace("Bearer ", ""))
                user_data.update(
                    {
                        "user_id": str(user_dto.id),
                        "username": getattr(user_dto, "username", None),
                    }
                )
            except Exception as e:
                logging.debug("Failed to get user from token: %s", e)

        request.state.user_data = user_data
        request.state.device_id = request.headers.get("x-device-id")
        request.state.user_agent = request.headers.get("user-agent", "")

        base_context = {
            "request_id": request_id,
            **user_data,
            "client_ip": client_ip,
            "method": request.method,
            "endpoint": request.url.path,
            # "user_agent": request.headers.get("user-agent", ""),
            # Redact secrets that may travel in the query string (e.g. the RTDN
            # shared secret accepted as ?token= for Pub/Sub push) so they never
            # land in logs / proxies.
            "query_params": {
                k: (
                    "[redacted]"
                    if k.lower() in {"token", "secret", "password", "api_key", "access_token"}
                    else v
                )
                for k, v in request.query_params.items()
            },
        }

        if request.method not in ["GET", "OPTIONS"] or request.url.path.startswith("/api/"):
            base_context["user_agent"] = request.headers.get("user-agent", "")

        context_filter = ContextFilter(base_context)
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            handler.addFilter(context_filter)

        start_time = time.time()

        try:
            response = await call_next(request)
            process_time = time.time() - start_time

            # should_log = (
            #     response.status_code >= 400
            #     or process_time > 3.0
            #     or request.method not in ["GET", "OPTIONS"]
            # )

            # if should_log:
            log_data = {
                **base_context,
                "status_code": response.status_code,
                "response_time_seconds": round(process_time, 3),
                "response_size": int(response.headers.get("content-length", 0)),
            }

            if response.status_code >= 500:
                root_logger.exception("Server error", extra={"props": log_data})
            elif response.status_code >= 400:
                root_logger.warning("Client error", extra={"props": log_data})
            elif process_time > 1.0:
                root_logger.warning("Slow request (%ss)", process_time, extra={"props": log_data})
            else:
                root_logger.info("Request completed", extra={"props": log_data})

            REQUEST_COUNT.labels(
                method=request.method,
                endpoint=request.url.path,
                status_code=response.status_code,
            ).inc()

            REQUEST_DURATION.labels(method=request.method, endpoint=request.url.path).observe(process_time)

            return response

        except Exception as e:
            process_time = time.time() - start_time

            ERROR_COUNT.labels(
                method=request.method,
                endpoint=request.url.path,
                error_type=type(e).__name__,
            ).inc()

            root_logger.exception(
                "Request failed: %s",
                str(e),
                extra={
                    "props": {
                        **base_context,
                        "status_code": 500,
                        "response_time_seconds": round(process_time, 3),
                        "error_type": type(e).__name__,
                    }
                },
            )
            raise
        finally:
            for handler in root_logger.handlers:
                handler.removeFilter(context_filter)


def get_client_ip(request: Request) -> str:
    if request.headers.get("x-forwarded-for"):
        return request.headers["x-forwarded-for"].split(",")[0]
    elif request.headers.get("x-real-ip"):
        return request.headers["x-real-ip"]
    else:
        return request.client.host if request.client else "unknown"


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        response = await call_next(request)
        process_time = time.time() - start_time

        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=request.url.path,
            status_code=response.status_code,
        ).inc()

        REQUEST_DURATION.labels(method=request.method, endpoint=request.url.path).observe(process_time)

        return response


def setup_metrics(app: FastAPI) -> FastAPI:
    import os

    _metrics_token = os.getenv("METRICS_TOKEN", "")

    @app.get(
        "/metrics",
        description="Prometheus metrics (requires X-Metrics-Token header)",
        tags=["System"],
        include_in_schema=False,
    )
    async def metrics(request: Request):
        if _metrics_token:
            provided = request.headers.get("X-Metrics-Token", "")
            if not provided or provided != _metrics_token:
                return Response(status_code=401)
        return Response(generate_latest(), media_type="text/plain")

    return app


class ContextFilter(logging.Filter):
    def __init__(self, context):
        super().__init__()
        self.context = context

    def filter(self, record):
        if not hasattr(record, "props"):
            record.props = {}
        record.props.update(self.context)
        return True


def log_with_context(level: int, message: str, **additional_context):
    extra_context = {"props": additional_context}
    logging.log(level, message, extra=extra_context)


def log_info(message: str, **context):
    log_with_context(logging.INFO, message, **context)


def log_warning(message: str, **context):
    log_with_context(logging.WARNING, message, **context)


def log_error(message: str, **context):
    log_with_context(logging.ERROR, message, **context)


# def log_debug(message: str, **context):
#     log_with_context(logging.DEBUG, message, **context)
