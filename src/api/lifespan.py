import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes.payments.websocket.manager import manager
from clients.freedom_pay.poller import start_poller_on_app, stop_poller_on_app
from database.settings import DatabaseSettings
from settings import Settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    settings = Settings()
    db_settings = DatabaseSettings(uri=settings.database.uri)

    start_poller_on_app(app, settings.freedom_pay, db_settings)
    await manager.start_heartbeat()

    notification_scheduler = app.state.container.daily_test_notification_scheduler()
    try:
        notification_scheduler.start()
    except RuntimeError:
        logger.exception("Failed to start daily test notification scheduler")

    yield

    stop_poller_on_app(app)
    await manager.stop_heartbeat()
    await notification_scheduler.stop()
