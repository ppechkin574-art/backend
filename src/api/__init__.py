import logging
import os

from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded
from starlette.middleware.cors import CORSMiddleware

from api.containers import Container
from api.exceptions.handlers import setup_exception_handlers
from api.lifespan import lifespan
from api.middlewares.exception_logging_middleware import ExceptionLoggingMiddleware
from api.middlewares.rate_limit import (
    custom_rate_limit_exceeded_handler,
    limiter,
    log_storage_choice,
)
from settings import Settings
from utils.monitoring import (
    LoggingContextMiddleware,
    setup_logging,
    setup_metrics,
)

from .routes import routers


def _init_sentry() -> None:
    """Initialise Sentry SDK if SENTRY_DSN is configured.

    No-op if the env var is missing — for local dev / first deploy before
    the Sentry project exists. Safe to leave unset; sampling defaults are
    cost-conservative.
    """
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        logging.getLogger(__name__).info(
            "[sentry] SENTRY_DSN not set — skipping Sentry init"
        )
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        sentry_sdk.init(
            dsn=dsn,
            environment=os.getenv("RAILWAY_ENVIRONMENT_NAME", "production"),
            release=os.getenv("RAILWAY_GIT_COMMIT_SHA", "unknown")[:8],
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.05")),
            profiles_sample_rate=0.0,
            send_default_pii=False,
            integrations=[
                StarletteIntegration(transaction_style="endpoint"),
                FastApiIntegration(transaction_style="endpoint"),
            ],
        )
        logging.getLogger(__name__).info(
            "[sentry] initialised — env=%s release=%s",
            os.getenv("RAILWAY_ENVIRONMENT_NAME", "production"),
            (os.getenv("RAILWAY_GIT_COMMIT_SHA") or "unknown")[:8],
        )
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "[sentry] init failed (non-fatal): %s", exc
        )


def create_app() -> FastAPI:
    setup_logging()
    _init_sentry()
    settings = Settings()
    container = Container()
    container.init_resources()

    uvicorn_loggers = [
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "uvicorn.asgi",
        "uvicorn.server",
    ]

    for logger_name in uvicorn_loggers:
        logger = logging.getLogger(logger_name)
        logger.handlers = []
        logger.propagate = False
        logger.setLevel(logging.CRITICAL)

    app = FastAPI(
        title="AIMA API",
        version="0.1.3",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        swagger_ui_parameters={
            "defaultModelsExpandDepth": -1,
            "deepLinking": True,
            "displayRequestDuration": True,
            "filter": True,
        },
        openapi_prefix="",
        root_path="",
        lifespan=lifespan,
    )
    app.state.container = container
    app.state.limiter = limiter
    # Custom 429 handler instead of slowapi's default — adds Retry-After
    # header (RFC 7231) and `retry_after_seconds` in body so mobile/web
    # clients can render accurate countdown UIs without hardcoding limits
    # per-endpoint. See `custom_rate_limit_exceeded_handler` for shape.
    app.add_exception_handler(RateLimitExceeded, custom_rate_limit_exceeded_handler)
    log_storage_choice()
    logging.getLogger(__name__).info(
        "[rate-limit] limiter wired: %s",
        [(r.path, r.methods) for r in app.routes if hasattr(r, "path") and "code/request" in r.path or (hasattr(r, "path") and "/auth/login" in r.path)] or "no-routes-yet (registered after include_router)",
    )

    app.add_middleware(LoggingContextMiddleware)
    app.add_middleware(
        ExceptionLoggingMiddleware,
        notifier=container.notification_client(),
        notifier_receiver_phone="",
    )

    # CORS — production-safe whitelist only.
    # `allowed_origins` env var must be a comma-separated list of explicit
    # origins (e.g. "https://aima.kz,https://admin.aima.kz"). The wildcard
    # fallback that previously kicked in when the env var was unset/`*` is
    # deliberately gone: it allowed any site to hit the API on the user's
    # behalf, which is a CSRF/credential-leak vector. If the variable is
    # unset or contains "*", we hard-fail at boot rather than silently
    # opening the door.
    origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
    if not origins or "*" in origins:
        raise RuntimeError(
            "ALLOWED_ORIGINS env var must be set to an explicit "
            "comma-separated list of origins. Wildcard ('*' or empty) is "
            "rejected to prevent CORS-based credential theft. "
            "Set it in Railway → Variables, e.g. "
            "ALLOWED_ORIGINS=https://aima.kz,https://admin.aima.kz"
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    setup_exception_handlers(app)
    setup_metrics(app)

    for router in routers:
        app.include_router(router)

    return app
