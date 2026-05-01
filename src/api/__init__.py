import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from api.containers import Container
from api.exceptions.handlers import setup_exception_handlers
from api.lifespan import lifespan
from api.middlewares.exception_logging_middleware import ExceptionLoggingMiddleware
from settings import Settings
from utils.monitoring import (
    LoggingContextMiddleware,
    setup_logging,
    setup_metrics,
)

from .routes import routers


def create_app() -> FastAPI:
    setup_logging()
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

    app.mount("/uploads", StaticFiles(directory="/app/uploads"), name="uploads")

    for router in routers:
        app.include_router(router)

    return app
