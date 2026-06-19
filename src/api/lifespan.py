import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI

from api.routes.payments.websocket.manager import manager
from clients.freedom_pay.poller import start_poller_on_app, stop_poller_on_app
from clients.notification import CodePlatform
from clients.notification.dtos import NotificationMessageDTO
from database.database import Database
from database.settings import DatabaseSettings
from settings import Settings

logger = logging.getLogger(__name__)

_DELETION_EXECUTOR_INTERVAL_SECONDS = 3600  # run every hour
_PAYMENT_WATCHDOG_INTERVAL_SECONDS = 86400  # daily


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


async def _payment_health_watchdog(
    db_settings: DatabaseSettings, settings: Settings, app: FastAPI
) -> None:
    """Daily payment health check (q12): summarise the last 24h of subscription
    events and ALERT when something is wrong.

    Reads the unified `subscription_event_log` (q10):
      - any `failed` events (verify rejected / activation failed = money taken
        but PRO maybe not granted) → ERROR log (→ Sentry) + Telegram alert.
      - zero successful events → WARNING (surfaces a possibly-broken gateway).
    Telegram delivery is best-effort: the alerts bot token is a stub today
    (`telegram_bot__TOKEN=changeme`), so until it's set this surfaces via the
    ERROR/WARNING logs (Sentry). Fully wired for when the token lands.
    """
    from subscription.event_log import SubscriptionEventLog  # noqa: PLC0415

    db = Database(db_settings)
    while True:
        await asyncio.sleep(_PAYMENT_WATCHDOG_INTERVAL_SECONDS)
        try:
            since = datetime.now(UTC) - timedelta(hours=24)
            with db.session as session:
                events = (
                    session.query(SubscriptionEventLog)
                    .filter(SubscriptionEventLog.created_at >= since)
                    .all()
                )
            ok = sum(1 for e in events if e.status == "success")
            failed = sum(1 for e in events if e.status == "failed")
            logger.info(
                "[payment-watchdog] last 24h: success=%s failed=%s total=%s",
                ok,
                failed,
                len(events),
            )

            alert_text: str | None = None
            if failed > 0:
                alert_text = (
                    f"⚠️ AIMA payments: {failed} FAILED event(s) in last 24h "
                    f"(success={ok}). Check subscription_event_log."
                )
                logger.error("[payment-watchdog] %s", alert_text)
            elif ok == 0:
                logger.warning(
                    "[payment-watchdog] ZERO successful payment events in last 24h"
                )

            if alert_text:
                try:
                    app.state.container.notification_client().notify(
                        NotificationMessageDTO(
                            to=str(settings.telegram_bot.chat_id),
                            message=f"<b>🚨 Payments</b>\n{alert_text}",
                            platform=CodePlatform.TELEGRAM,
                        )
                    )
                except Exception:  # noqa: BLE001 — alert delivery is best-effort
                    logger.exception("[payment-watchdog] Telegram alert failed")
        except Exception:  # noqa: BLE001
            logger.exception("[payment-watchdog] cycle error")


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
    payment_watchdog_task = asyncio.create_task(
        _payment_health_watchdog(db_settings, settings, app)
    )

    yield

    deletion_task.cancel()
    payment_watchdog_task.cancel()
    stop_poller_on_app(app)
    await manager.stop_heartbeat()
    await notification_scheduler.stop()
    await streak_reminder_scheduler.stop()
