import asyncio
import logging
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

_DELETION_EXECUTOR_INTERVAL_SECONDS = 3600   # run every hour
_PAYMENT_WATCHDOG_INTERVAL_SECONDS  = 86400  # daily
_SUSPICIOUS_SUB_INTERVAL_SECONDS    = 3600   # every hour
_ACTIVITY_CLEANUP_INTERVAL_SECONDS  = 86400  # daily
_POINTS_RESET_CHECK_INTERVAL_SECONDS = 3600  # hourly — cheap no-op when not due


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


async def _suspicious_subscription_checker(db_settings: DatabaseSettings) -> None:
    """Hourly: find active PRO subscriptions with no payment and no promo code."""
    from database.database import Database
    from payments.models import Payment
    from promocodes.models import PromocodeUsage
    from security.models import FraudEvent
    from security.repository import FraudEventRepository
    from subscription.models import Subscription

    db = Database(db_settings)
    while True:
        await asyncio.sleep(_SUSPICIOUS_SUB_INTERVAL_SECONDS)
        try:
            from datetime import UTC, datetime, timedelta

            from sqlalchemy import cast, exists
            from sqlalchemy.dialects.postgresql import UUID as PG_UUID

            session = db.session
            try:
                now = datetime.now(UTC)
                suspects = (
                    session.query(Subscription.user_id)
                    .filter(
                        Subscription.plan == "PRO",
                        Subscription.status == "active",
                        Subscription.expires_at > now,
                        Subscription.payment_id.is_(None),
                        Subscription.promocode_usage_id.is_(None),
                        ~exists().where(
                            (Payment.user_id == Subscription.user_id)
                            & (Payment.status == "completed")
                        ),
                        ~exists().where(
                            PromocodeUsage.student_guid
                            == cast(Subscription.user_id, PG_UUID(as_uuid=True))
                        ),
                        # Skip users already alerted in the last 24h
                        ~exists().where(
                            (FraudEvent.user_id
                             == cast(Subscription.user_id, PG_UUID(as_uuid=True)))
                            & (FraudEvent.event_type == "pro_without_payment")
                            & (FraudEvent.created_at > (now - timedelta(hours=24)))
                        ),
                    )
                    .limit(50)
                    .all()
                )
                if suspects:
                    repo = FraudEventRepository(session)
                    for (user_id,) in suspects:
                        try:
                            import uuid
                            repo.log_event(
                                event_type="pro_without_payment",
                                risk_score=80,
                                user_id=uuid.UUID(str(user_id)),
                                reason=(
                                    "Active PRO subscription with no completed payment "
                                    "and no promo code redemption on record"
                                ),
                                metadata={"user_id": str(user_id), "detected_at": now.isoformat()},
                            )
                        except Exception:
                            logger.exception(
                                "pro_without_payment log failed for user=%s", user_id
                            )
                    session.commit()
                    logger.info(
                        "[suspicious-sub-check] flagged %d users", len(suspects)
                    )
            finally:
                session.close()
        except Exception:
            logger.exception("[suspicious-sub-check] cycle error")


async def _cleanup_old_activity_events(db_settings: DatabaseSettings) -> None:
    """Daily: delete user_activity_events older than 90 days to keep the table small."""
    from sqlalchemy import text as _text

    db = Database(db_settings)
    while True:
        await asyncio.sleep(_ACTIVITY_CLEANUP_INTERVAL_SECONDS)
        try:
            cutoff = datetime.now(UTC) - timedelta(days=90)
            with db.session as session:
                result = session.execute(
                    _text("DELETE FROM user_activity_events WHERE occurred_at < :cutoff"),
                    {"cutoff": cutoff},
                )
                session.commit()
                deleted = result.rowcount
            if deleted:
                logger.info("Activity cleanup: deleted %d events older than 90 days", deleted)
        except Exception:
            logger.exception("Activity cleanup failed (non-fatal)")


async def _points_auto_reset_check(db_settings: DatabaseSettings) -> None:
    """Hourly: reset every user's leaderboard points to 0 once the
    admin-configured schedule is due — either a fixed N-day interval, or
    (for the "Еженедельный спринт") every Monday 00:00 Asia/Almaty.
    No-op (cheap) when auto-reset is disabled or not yet due — see
    LeaderboardPointsService."""
    from leaderboard_points.repository import LeaderboardPointsRepository
    from leaderboard_points.service import LeaderboardPointsService

    db = Database(db_settings)
    while True:
        await asyncio.sleep(_POINTS_RESET_CHECK_INTERVAL_SECONDS)
        try:
            with db.session as session:
                service = LeaderboardPointsService(LeaderboardPointsRepository(session))
                result = service.reset_all_points_if_due()
                if result.ran:
                    session.commit()
                    logger.info(
                        "[points-auto-reset] reset %d users, next reset at %s",
                        result.users_reset,
                        result.next_reset_at,
                    )
        except Exception:
            logger.exception("[points-auto-reset] cycle error")


async def _sprint_week_close_check(db_settings: DatabaseSettings) -> None:
    """Hourly: resolve the weekly sprint week that has just ended (CRM #19).

    Only ever looks at the PREVIOUS calendar week and does nothing once
    that week already has a winner row, so running every hour is cheap and
    idempotent — the first cycle after Monday 00:00 Almaty does the work,
    the rest are no-ops. Polling rather than firing exactly at midnight is
    deliberate: a missed tick (deploy, restart) still gets picked up within
    the hour instead of losing the week entirely.

    Independent of the points auto-reset above: the sprint is decided off
    the calendar week and off `points_audit_log`, so it resolves correctly
    whether or not auto-reset is enabled."""
    from leaderboard_points.repository import LeaderboardPointsRepository
    from leaderboard_points.sprint import SprintService

    db = Database(db_settings)
    while True:
        await asyncio.sleep(_POINTS_RESET_CHECK_INTERVAL_SECONDS)
        try:
            with db.session as session:
                result = SprintService(
                    LeaderboardPointsRepository(session)
                ).close_week_if_due()
                if result.get("ran"):
                    session.commit()
                    logger.info(
                        "[sprint-week-close] %s, winners: %s",
                        result.get("resolution"),
                        result.get("winners"),
                    )
        except Exception:
            logger.exception("[sprint-week-close] cycle error")


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
    suspicious_sub_task = asyncio.create_task(
        _suspicious_subscription_checker(db_settings)
    )
    activity_cleanup_task = asyncio.create_task(
        _cleanup_old_activity_events(db_settings)
    )
    points_auto_reset_task = asyncio.create_task(
        _points_auto_reset_check(db_settings)
    )
    sprint_week_close_task = asyncio.create_task(
        _sprint_week_close_check(db_settings)
    )

    yield

    deletion_task.cancel()
    payment_watchdog_task.cancel()
    suspicious_sub_task.cancel()
    activity_cleanup_task.cancel()
    points_auto_reset_task.cancel()
    sprint_week_close_task.cancel()
    stop_poller_on_app(app)
    await manager.stop_heartbeat()
    await notification_scheduler.stop()
    await streak_reminder_scheduler.stop()
