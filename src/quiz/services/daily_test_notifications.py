import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from clients.firebase import FirebaseNotificationClient
from clients.firebase.settings import FirebaseSettings
from database import Database
from quiz.repositories.daily_tests import DailyTestRepository

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DailyTestNotificationResult:
    requested: int
    delivered: int
    failed: int
    removed_tokens: int


class DailyTestNotificationService:
    """Сервис отправки push-уведомлений о новых ежедневных тестах."""

    def __init__(
        self,
        database: Database,
        firebase_client: FirebaseNotificationClient,
        firebase_settings: FirebaseSettings,
    ) -> None:
        self._database = database
        self._firebase_client = firebase_client
        self._firebase_settings = firebase_settings

    @property
    def enabled(self) -> bool:
        return self._firebase_client.enabled

    def send_daily_notifications(
        self,
        *,
        title: str | None = None,
        body: str | None = None,
        data: dict[str, str] | None = None,
    ) -> DailyTestNotificationResult:
        if not self.enabled:
            logger.warning("Firebase notifications disabled, skip broadcast")
            return DailyTestNotificationResult(0, 0, 0, 0)

        session = self._database.session
        repo = DailyTestRepository(session)
        fetch_size = max(100, self._firebase_settings.fetch_chunk_size)
        last_id: int | None = None

        total_requested = total_success = total_failure = removed = 0
        invalid_tokens: list[str] = []

        try:
            while True:
                batch = repo.fetch_device_tokens(last_id=last_id, limit=fetch_size)
                if not batch:
                    break

                tokens = [row.token for row in batch if row.token]
                last_id = batch[-1].id

                if not tokens:
                    continue

                send_result = self._firebase_client.broadcast(
                    tokens,
                    title=title,
                    body=body,
                    data=data or {"type": "daily_test"},
                )
                total_requested += send_result.requested
                total_success += send_result.success
                total_failure += send_result.failure
                invalid_tokens.extend(send_result.invalid_tokens)

            if invalid_tokens:
                removed = repo.delete_tokens(invalid_tokens)
        finally:
            session.close()

        return DailyTestNotificationResult(
            requested=total_requested,
            delivered=total_success,
            failed=total_failure,
            removed_tokens=removed,
        )


class DailyTestNotificationScheduler:
    """Простой планировщик, который шлет уведомления каждый день в 9:00 по Астане."""

    def __init__(
        self,
        notification_service: DailyTestNotificationService,
        firebase_settings: FirebaseSettings,
    ) -> None:
        self._service = notification_service
        self._settings = firebase_settings
        self._timezone = ZoneInfo(firebase_settings.timezone)
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        if not self._service.enabled:
            logger.warning("Skipping daily test notification scheduler (disabled)")
            return

        if self._task and not self._task.done():
            return

        loop = asyncio.get_running_loop()
        self._stop_event.clear()
        self._task = loop.create_task(self._runner())
        logger.info(
            "Daily test notification scheduler started with target %02d:%02d %s",
            self._settings.notification_hour,
            self._settings.notification_minute,
            self._settings.timezone,
        )

    async def stop(self) -> None:
        if not self._task:
            return

        self._stop_event.set()
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("Daily test notification scheduler stopped")

    # async def trigger_now(self) -> DailyTestNotificationResult | None:
    #     if not self._service.enabled:
    #         logger.warning("Cannot trigger notifications manually, firebase disabled")
    #         return None
    #     return await asyncio.to_thread(self._service.send_daily_notifications)

    async def _runner(self) -> None:
        while not self._stop_event.is_set():
            wait_seconds = self._seconds_until_target()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait_seconds)
                if self._stop_event.is_set():
                    break
            except TimeoutError:
                pass

            if self._stop_event.is_set():
                break

            try:
                result = await asyncio.to_thread(self._service.send_daily_notifications)
                logger.info(
                    "Daily test notifications sent: requested=%s delivered=%s failed=%s removed=%s",
                    result.requested,
                    result.delivered,
                    result.failed,
                    result.removed_tokens,
                )
            except Exception:  # pragma: no cover - logging + retry
                logger.exception("Failed to send scheduled daily test notifications")

    def _seconds_until_target(self) -> float:
        now = datetime.now(self._timezone)
        target = now.replace(
            hour=self._settings.notification_hour,
            minute=self._settings.notification_minute,
            second=0,
            microsecond=0,
        )
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()
