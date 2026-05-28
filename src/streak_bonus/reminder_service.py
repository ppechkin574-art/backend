"""Streak-reminder cron — pushes «не теряй стрик» FCM N hours before
the local-day rollover.

Wires together three independently-stored pieces:
- `streak_push_template`            operator-editable copy + offset
- `attendance_streaks`              who has an active streak
- `streak_bonus_claims`             who already claimed today (excluded)
- `daily_test_device_tokens`        FCM endpoint per student

Body supports a `{streak}` placeholder; service groups the audience
by current streak length so each multicast call sends one personalized
body to all users with the same streak count — keeps the multicast
batches efficient without losing personalization.

The scheduler re-reads `streak_push_template` at every tick so admin
edits to the offset/title/body take effect on the next daily fire
without redeploying.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from clients.firebase import FirebaseNotificationClient
from database import Database
from quiz.models.attendance_streak import AttendanceStreak
from quiz.models.daily_tests import DailyTestDeviceToken
from streak_bonus.models import StreakBonusClaim, StreakPushTemplate

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class StreakReminderResult:
    requested: int
    delivered: int
    failed: int
    skipped_disabled: bool = False


class StreakReminderService:
    """Worker that sends the streak-reminder broadcast in one synchronous
    pass. The scheduler wraps it in `asyncio.to_thread` to keep the FastAPI
    event loop free."""

    def __init__(
        self,
        database: Database,
        firebase_client: FirebaseNotificationClient,
    ) -> None:
        self._database = database
        self._firebase_client = firebase_client

    def send_streak_reminders(self) -> StreakReminderResult:
        if not self._firebase_client.enabled:
            logger.warning("Firebase disabled, skipping streak reminder cron")
            return StreakReminderResult(0, 0, 0, skipped_disabled=True)

        session: Session = self._database.session
        try:
            template = session.get(StreakPushTemplate, 1)
            if template is None or not template.enabled:
                logger.info("Streak reminder template disabled, skipping")
                return StreakReminderResult(0, 0, 0, skipped_disabled=True)

            today_local = self._today_in_tz(template.timezone)

            # streak ≥ 1 AND no claim row for today → audience.
            claim_subq = (
                select(StreakBonusClaim.user_id)
                .where(StreakBonusClaim.claim_date == today_local)
                .scalar_subquery()
            )
            rows = session.execute(
                select(
                    AttendanceStreak.student_guid,
                    AttendanceStreak.current_streak_days,
                )
                .where(AttendanceStreak.current_streak_days >= 1)
                .where(AttendanceStreak.student_guid.notin_(claim_subq))
            ).all()

            if not rows:
                logger.info("Streak reminder: no audience for %s", today_local)
                return StreakReminderResult(0, 0, 0)

            # Group student_guid → streak so we can render one body per group.
            students_by_streak: dict[int, list] = defaultdict(list)
            for student_guid, streak in rows:
                students_by_streak[int(streak)].append(student_guid)

            total_requested = total_delivered = total_failed = 0
            for streak, students in students_by_streak.items():
                tokens = self._fetch_tokens(session, students)
                if not tokens:
                    continue

                title = self._render(template.title, streak=streak)
                body = self._render(template.body, streak=streak)

                # FCM multicast caps at 500; chunk locally even though
                # the daily-test cron settings would normally enforce it.
                for chunk in _chunked(tokens, 500):
                    result = self._firebase_client.send_multicast(
                        chunk,
                        title=title,
                        body=body,
                        data={
                            "type": "streak_reminder",
                            "streak": str(streak),
                        },
                    )
                    total_requested += result.requested
                    total_delivered += result.success
                    total_failed += result.failure

            logger.info(
                "Streak reminder sent: requested=%s delivered=%s failed=%s",
                total_requested,
                total_delivered,
                total_failed,
            )
            return StreakReminderResult(
                requested=total_requested,
                delivered=total_delivered,
                failed=total_failed,
            )
        finally:
            session.close()

    # ─── helpers ────────────────────────────────────────────────────

    @staticmethod
    def _render(template_str: str, *, streak: int) -> str:
        # Forgiving format — operator may or may not use {streak} in copy.
        try:
            return template_str.format(streak=streak)
        except (KeyError, IndexError):
            return template_str

    @staticmethod
    def _today_in_tz(tz_name: str) -> date:
        return datetime.now(ZoneInfo(tz_name)).date()

    @staticmethod
    def _fetch_tokens(session: Session, student_guids: list) -> list[str]:
        rows = session.scalars(
            select(DailyTestDeviceToken.token).where(
                DailyTestDeviceToken.student_guid.in_(student_guids)
            )
        ).all()
        return [t for t in rows if t]

    # ─── QA helpers ─────────────────────────────────────────────────

    def send_test_to_user(
        self, user_id, fake_streak: int = 5
    ) -> StreakReminderResult:
        """Test-send: rendering uses `fake_streak`, audience is just
        the given user's FCM tokens. Bypasses the attendance_streaks /
        claims filter so it works for QA accounts whose streak column
        wasn't bumped by seed-streak (seed only writes attempt rows)."""
        if not self._firebase_client.enabled:
            return StreakReminderResult(0, 0, 0, skipped_disabled=True)

        session: Session = self._database.session
        try:
            template = session.get(StreakPushTemplate, 1)
            if template is None:
                return StreakReminderResult(0, 0, 0, skipped_disabled=True)

            tokens = self._fetch_tokens(session, [user_id])
            if not tokens:
                logger.info("Streak reminder test: no FCM tokens for %s", user_id)
                return StreakReminderResult(0, 0, 0)

            title = self._render(template.title, streak=fake_streak)
            body = self._render(template.body, streak=fake_streak)
            result = self._firebase_client.send_multicast(
                tokens,
                title=title,
                body=body,
                data={
                    "type": "streak_reminder",
                    "streak": str(fake_streak),
                    "test": "true",
                },
            )
            return StreakReminderResult(
                requested=result.requested,
                delivered=result.success,
                failed=result.failure,
            )
        finally:
            session.close()


def _chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


class StreakReminderScheduler:
    """Fires `send_streak_reminders` daily at `(midnight - offset)` in the
    template's timezone. Re-reads the template each tick so admin edits
    to `hours_before_reset` apply on the next cycle without a redeploy."""

    def __init__(
        self,
        database: Database,
        reminder_service: StreakReminderService,
    ) -> None:
        self._database = database
        self._service = reminder_service
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        loop = asyncio.get_running_loop()
        self._stop_event.clear()
        self._task = loop.create_task(self._runner())
        logger.info("Streak reminder scheduler started")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop_event.set()
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("Streak reminder scheduler stopped")

    async def _runner(self) -> None:
        while not self._stop_event.is_set():
            wait_seconds = self._seconds_until_target()
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=wait_seconds,
                )
                if self._stop_event.is_set():
                    break
            except TimeoutError:
                pass

            if self._stop_event.is_set():
                break

            try:
                await asyncio.to_thread(self._service.send_streak_reminders)
            except Exception:  # pragma: no cover
                logger.exception("Streak reminder cron failed")

    def _seconds_until_target(self) -> float:
        """`(local midnight + 1 day) - hours_before_reset`."""
        session: Session = self._database.session
        try:
            template = session.get(StreakPushTemplate, 1)
            tz_name = template.timezone if template else "Asia/Almaty"
            hours_before = template.hours_before_reset if template else 8
        finally:
            session.close()

        tz = ZoneInfo(tz_name)
        now = datetime.now(tz)
        next_midnight = (
            now.replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(days=1)
        )
        target = next_midnight - timedelta(hours=hours_before)
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()
