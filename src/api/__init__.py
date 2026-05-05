import logging
import os

from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.cors import CORSMiddleware

from api.containers import Container
from api.exceptions.handlers import setup_exception_handlers
from api.lifespan import lifespan
from api.middlewares.exception_logging_middleware import ExceptionLoggingMiddleware
from api.middlewares.rate_limit import limiter, log_storage_choice
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
        title="Lumi API",
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
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
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

    origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
    cors_kwargs: dict = {
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }
    if not origins or "*" in origins:
        cors_kwargs["allow_origin_regex"] = ".*"
        cors_kwargs["allow_credentials"] = False
    else:
        cors_kwargs["allow_origins"] = origins
        cors_kwargs["allow_credentials"] = True

    app.add_middleware(CORSMiddleware, **cors_kwargs)

    setup_exception_handlers(app)
    setup_metrics(app)

    for router in routers:
        app.include_router(router)

    return app
