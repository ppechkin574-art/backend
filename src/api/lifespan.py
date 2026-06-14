import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI

from api.routes.payments.websocket.manager import manager
from clients.freedom_pay.poller import start_poller_on_app, stop_poller_on_app
from database.database import Database
from database.settings import DatabaseSettings
from settings import Settings

logger = logging.getLogger(__name__)

_DELETION_EXECUTOR_INTERVAL_SECONDS = 3600  # run every hour


async def _execute_scheduled_deletions(db_settings: DatabaseSettings, app: FastAPI) -> None:
    """Background task: hard-delete Keycloak accounts whose grace period has elapsed."""
    from auth.deletion_models import AccountDeletionRequest

    db = Database(db_settings)
    while True:
        await asyncio.sleep(_DELETION_EXECUTOR_INTERVAL_SECONDS)
        try:
            identity_provider = app.state.container.identity_provider_client()
            with db.session as session:
                now = datetime.now(UTC)
                pending = (
                    session.query(AccountDeletionRequest)
                    .filter(
                        AccountDeletionRequest.scheduled_for <= now,
                        AccountDeletionRequest.executed_at.is_(None),
                    )
                    .all()
                )
                for req in pending:
                    try:
                        identity_provider.delete(req.user_id)
                        req.executed_at = now
                        session.commit()
                        logger.info(
                            "Scheduled account deletion executed: user=%s", req.user_id
                        )
                    except Exception:
                        logger.exception(
                            "Failed to hard-delete account %s (will retry next cycle)",
                            req.user_id,
                        )
        except Exception:
            logger.exception("Deletion executor cycle error")


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

    streak_reminder_scheduler = app.state.container.streak_reminder_scheduler()
    try:
        streak_reminder_scheduler.start()
    except RuntimeError:
        logger.exception("Failed to start streak reminder scheduler")

    deletion_task = asyncio.create_task(
        _execute_scheduled_deletions(db_settings, app)
    )

    yield

    deletion_task.cancel()
    stop_poller_on_app(app)
    await manager.stop_heartbeat()
    await notification_scheduler.stop()
    await streak_reminder_scheduler.stop()
