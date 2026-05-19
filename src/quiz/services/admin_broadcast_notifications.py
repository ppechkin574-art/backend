"""Admin-facing broadcast push notification service.

Sits next to `daily_test_notifications.py` (which the scheduled daily
job uses). The split exists to keep the daily-cron's send path stable
while the admin path evolves — targeting, scheduling, deep links,
templates etc. live here without touching the cron service.

19.05.2026: introduced after operator surfaced the need for ad-hoc
marketing pushes from the admin panel. Apple's 1.2.1 submission was
under review at the time, so the design deliberately keeps the
existing `/admin/notifications/test/send` endpoint and
`DailyTestNotificationService` untouched.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from clients.firebase import FirebaseNotificationClient
from clients.firebase.settings import FirebaseSettings
from clients.identity_provider.client import IdentityProviderClientKeycloak
from common.enums import PlanType
from database import Database
from quiz.models.daily_tests import DailyTestDeviceToken
from quiz.repositories.daily_tests import DailyTestRepository

logger = logging.getLogger(__name__)


BroadcastTarget = Literal["all", "pro", "ios"]


@dataclass(slots=True)
class BroadcastResult:
    target: BroadcastTarget
    matched_tokens: int  # how many tokens passed the target filter
    requested: int  # how many actually attempted to send (FCM API call)
    delivered: int
    failed: int
    removed_tokens: int


class AdminBroadcastNotificationService:
    """Send a push to a filtered slice of the user base.

    Target options:
      - ``all``  — every FCM token currently registered.
      - ``ios``  — tokens whose `platform == 'ios'`.
      - ``pro``  — tokens whose owning user has `plan = PRO` in
        Keycloak. The plan attribute lives in Keycloak (not Postgres),
        so we fetch all users in one Keycloak admin call and build a
        membership set in-memory. Acceptable while user count is in
        the low thousands; if/when that grows past ~50k, switch to
        caching plan in Postgres on every login (see ADMIN_TASKS.md).
    """

    def __init__(
        self,
        database: Database,
        firebase_client: FirebaseNotificationClient,
        firebase_settings: FirebaseSettings,
        identity_provider: IdentityProviderClientKeycloak,
    ) -> None:
        self._database = database
        self._firebase_client = firebase_client
        self._firebase_settings = firebase_settings
        self._idp = identity_provider

    @property
    def enabled(self) -> bool:
        return self._firebase_client.enabled

    def send(
        self,
        *,
        title: str,
        body: str,
        target: BroadcastTarget = "all",
        data: dict[str, str] | None = None,
    ) -> BroadcastResult:
        if not self.enabled:
            logger.warning("Firebase notifications disabled, refusing to broadcast")
            return BroadcastResult(target, 0, 0, 0, 0, 0)

        # Resolve the membership set ONCE up front. For `all` and
        # `ios` no Keycloak round-trip is needed; for `pro` we fetch
        # the whole user list and snapshot the PRO subset.
        pro_user_ids: set[str] | None = None
        if target == "pro":
            pro_user_ids = self._fetch_pro_user_ids()
            if not pro_user_ids:
                logger.info("No PRO users found — nothing to send")
                return BroadcastResult(target, 0, 0, 0, 0, 0)

        session = self._database.session
        repo = DailyTestRepository(session)
        fetch_size = max(100, self._firebase_settings.fetch_chunk_size)
        last_id: int | None = None

        matched = total_requested = total_success = total_failure = removed = 0
        invalid_tokens: list[str] = []

        try:
            while True:
                batch = repo.fetch_device_tokens(last_id=last_id, limit=fetch_size)
                if not batch:
                    break

                filtered = self._apply_target_filter(
                    batch, target=target, pro_user_ids=pro_user_ids
                )
                tokens = [row.token for row in filtered if row.token]
                last_id = batch[-1].id
                matched += len(tokens)

                if not tokens:
                    continue

                send_result = self._firebase_client.broadcast(
                    tokens,
                    title=title,
                    body=body,
                    data=data or {"type": "admin_broadcast", "target": target},
                )
                total_requested += send_result.requested
                total_success += send_result.success
                total_failure += send_result.failure
                invalid_tokens.extend(send_result.invalid_tokens)

            if invalid_tokens:
                removed = repo.delete_tokens(invalid_tokens)
        finally:
            session.close()

        return BroadcastResult(
            target=target,
            matched_tokens=matched,
            requested=total_requested,
            delivered=total_success,
            failed=total_failure,
            removed_tokens=removed,
        )

    # ─────────────────────── helpers ───────────────────────

    @staticmethod
    def _apply_target_filter(
        rows: list[DailyTestDeviceToken],
        *,
        target: BroadcastTarget,
        pro_user_ids: set[str] | None,
    ) -> list[DailyTestDeviceToken]:
        if target == "all":
            return rows
        if target == "ios":
            # Case-insensitive — Flutter sometimes sends "iOS" / "ios"
            return [r for r in rows if (r.platform or "").lower() == "ios"]
        if target == "pro":
            ids = pro_user_ids or set()
            return [r for r in rows if str(r.student_guid) in ids]
        # Defensive: unknown target → empty (caller bug)
        logger.warning("Unknown broadcast target %r — returning no rows", target)
        return []

    def _fetch_pro_user_ids(self) -> set[str]:
        """Pull all users from Keycloak in one admin call and return
        the subset with plan=PRO. Heavy (linear in total users) but
        called at most once per broadcast — fine while we're under
        ~50k users. The alternative is a Postgres-side cache of
        `plan` on the user record, which is a separate refactor.
        """
        try:
            users = self._idp.get_users()
        except Exception:
            logger.exception("Failed to fetch users for PRO filter")
            return set()

        pro_ids: set[str] = set()
        for u in users:
            attrs = getattr(u, "attributes", None)
            if not attrs:
                continue
            plan_list = getattr(attrs, "plan", None)
            if not plan_list:
                continue
            first = plan_list[0] if isinstance(plan_list, list) else plan_list
            if str(first).upper() == PlanType.PRO.value.upper():
                user_id = getattr(u, "id", None)
                if user_id:
                    pro_ids.add(str(user_id))
        return pro_ids
