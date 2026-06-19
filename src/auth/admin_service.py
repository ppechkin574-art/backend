import logging
import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from auth.converters import to_keycloak_create_user_dto, to_user_dto
from auth.dtos.admin import (
    AdminUserCreateDTO,
    AdminUserCreateResponseDTO,
    AdminUserUpdateDTO,
)
from auth.dtos.users import UserCreateDTO, UserDTO
from clients.identity_provider.client import IdentityProviderClientKeycloak
from clients.identity_provider.dtos import (
    KeycloakAttributesUpdateDTO,
    KeycloakUserQueryDTO,
    KeycloakUserUpdateDTO,
)
from common.enums import PlanType
from quiz.repositories.user_points import UserPointsRepository

logger = logging.getLogger(__name__)


class AdminUserService:
    def __init__(
        self,
        identity_provider: IdentityProviderClientKeycloak,
        session: Session | None = None,
    ):
        self.identity_provider = identity_provider
        self._session = session

    def get_users(self, role: str | None = None, search: str | None = None) -> list[UserDTO]:
        raw_users = self.identity_provider.get_users()
        users = [to_user_dto(u, self.identity_provider.get_roles(u.id)) for u in raw_users]
        if role:
            users = [u for u in users if role in u.roles]
        if search:
            search_lower = search.lower()
            users = [
                u for u in users if search_lower in u.name.lower() or (u.email and search_lower in u.email.lower())
            ]
        if self._session and users:
            self._enrich_with_pg_stats(users)
        return users

    def _enrich_with_pg_stats(self, users: list[UserDTO]) -> None:
        """Batch-fetch per-user stats from PostgreSQL and merge into DTOs.

        Several batched queries for all users at once — no N+1. Each query is
        wrapped independently so a single missing/empty table degrades one
        column to its default instead of dropping every enriched field.

        Enriched columns:
          * attendance streak           ← attendance_streaks
          * leaderboard points + rank   ← user_points (the in-app "stars";
            NOT students.rating, which is the separate legacy trainer rating)
          * device / version / activity ← latest user_activity event, with a
            daily_test_device_tokens platform fallback
        """
        ids = [str(u.id) for u in users]
        id_list = ", ".join(f"'{uid}'" for uid in ids)

        # --- attendance streak ------------------------------------------
        streak_map: dict[str, tuple] = {}
        try:
            streak_rows = self._session.execute(
                text(
                    f"SELECT student_guid, current_streak_days, total_points "
                    f"FROM attendance_streaks WHERE student_guid IN ({id_list})"
                )
            ).fetchall()
            streak_map = {str(r[0]): (r[1], r[2]) for r in streak_rows}
        except Exception:
            logger.exception("enrich: attendance_streaks query failed")

        # --- leaderboard points + rank (user_points) --------------------
        # rank = number of users with strictly more points + 1, excluding
        # admin-hidden users (mirrors UserPointsRepository.get_user_rank).
        lb_map: dict[str, tuple] = {}
        try:
            lb_rows = self._session.execute(
                text(
                    f"SELECT up.user_id, up.total_points, "
                    f"  (SELECT COUNT(*) + 1 FROM user_points up2 "
                    f"   WHERE up2.total_points > up.total_points "
                    f"     AND up2.user_id NOT IN "
                    f"         (SELECT user_id FROM leaderboard_hidden_users)) AS rank "
                    f"FROM user_points up WHERE up.user_id IN ({id_list})"
                )
            ).fetchall()
            lb_map = {str(r[0]): (r[1], r[2]) for r in lb_rows}
        except Exception:
            logger.exception("enrich: user_points query failed")

        # --- latest analytics event: platform / os / version / activity -
        act_map: dict[str, tuple] = {}
        try:
            act_rows = self._session.execute(
                text(
                    f"SELECT DISTINCT ON (user_id) user_id, platform, os_version, "
                    f"  app_version, event_time "
                    f"FROM user_activity WHERE user_id IN ({id_list}) "
                    f"ORDER BY user_id, event_time DESC"
                )
            ).fetchall()
            act_map = {str(r[0]): (r[1], r[2], r[3], r[4]) for r in act_rows}
        except Exception:
            logger.exception("enrich: user_activity query failed")

        # --- device-token platform fallback (FCM registration) ----------
        dev_map: dict[str, str] = {}
        try:
            dev_rows = self._session.execute(
                text(
                    f"SELECT DISTINCT ON (student_guid) student_guid, platform "
                    f"FROM daily_test_device_tokens WHERE student_guid IN ({id_list}) "
                    f"ORDER BY student_guid, updated_at DESC"
                )
            ).fetchall()
            dev_map = {str(r[0]): r[1] for r in dev_rows if r[1]}
        except Exception:
            logger.exception("enrich: daily_test_device_tokens query failed")

        for u in users:
            uid = str(u.id)
            if uid in streak_map:
                u.attendance_streak_days = streak_map[uid][0] or 0
                u.attendance_total_points = streak_map[uid][1] or 0
            if uid in lb_map:
                u.points = lb_map[uid][0] or 0
                u.rank = lb_map[uid][1]
            act = act_map.get(uid)
            if act:
                u.device_platform = act[0]
                u.device_os_version = act[1]
                u.app_version = act[2]
                u.last_active_at = act[3]
            # Fall back to the registered push-token platform when analytics
            # carried none (e.g. user never sent a platform-tagged event).
            if not u.device_platform and uid in dev_map:
                u.device_platform = dev_map[uid]

    def create_user(self, data: AdminUserCreateDTO) -> AdminUserCreateResponseDTO:
        password = data.password
        generated = False
        if not password:
            password = uuid.uuid4().hex
            generated = True

        user_create_dto = UserCreateDTO(
            name=data.name,
            phone=data.phone,
            email=data.email,
            avatar=None,
            password=password,
            role=data.role,
            is_active=True,
            allowed_subject_ids=data.allowed_subject_ids or [],
            plan=PlanType.PRO,
            subscription_end=datetime.now(UTC) + timedelta(days=365),
            used_trial=False,
        )

        create_dto = to_keycloak_create_user_dto(user_create_dto)

        create_dto.attributes.allowed_subject_ids = (
            [str(sid) for sid in data.allowed_subject_ids] if data.allowed_subject_ids else []
        )
        create_dto.attributes.role = [data.role]

        try:
            created_user, _ = self.identity_provider.get_or_create(create_dto)
        except Exception as e:
            logger.exception("Failed to create user: %s", str(e))
            raise

        if data.role == "teacher":
            self.identity_provider.add_realm_role(created_user.id, "teacher")
        elif data.role == "admin":
            self.identity_provider.add_realm_role(created_user.id, "panel_admin")

        roles = self.identity_provider.get_roles(created_user.id)
        user_dto = to_user_dto(created_user, roles)

        response = AdminUserCreateResponseDTO(**user_dto.model_dump())
        if generated:
            response.generated_password = password
        return response

    def get_user(self, user_id: UUID) -> UserDTO:
        keycloak_user = self.identity_provider.get(KeycloakUserQueryDTO(id=user_id))
        roles = self.identity_provider.get_roles(user_id)
        return to_user_dto(keycloak_user, roles)

    def update_user(self, user_id: UUID, data: AdminUserUpdateDTO) -> UserDTO:
        keycloak_user = self.identity_provider.get(KeycloakUserQueryDTO(id=user_id))

        update_attrs = {}
        if data.name is not None:
            update_attrs["name"] = [data.name]
        if data.phone is not None:
            update_attrs["phone"] = [data.phone]
        if data.allowed_subject_ids is not None:
            update_attrs["allowed_subject_ids"] = [str(sid) for sid in data.allowed_subject_ids]

        if data.password:
            self.identity_provider.set_password(user_id, data.password)

        if data.is_active is not None:
            self.identity_provider.set_active(user_id, data.is_active)

        attributes_update = KeycloakAttributesUpdateDTO(**update_attrs) if update_attrs else None
        update_dto = KeycloakUserUpdateDTO(
            email=data.email if data.email is not None else keycloak_user.email,
            attributes=attributes_update,
        )
        self.identity_provider.update_user(user_id, update_dto)
        return self.get_user(user_id)

    def delete_user(self, user_id: UUID) -> None:
        self.identity_provider.delete(user_id)

    def reset_subscription(self, user_id: UUID) -> UserDTO:
        """Force-reset the user's subscription to FREE.

        Clears:
          - plan → "free"
          - subscription_end → unset (empty list)
          - subscription_cancelled → unset (empty list)

        Used to prepare the "Apple Reviewer" demo account before
        an App Store submission: the reviewer needs to see the
        "Купить подписку" CTA, but the account is already PRO with
        57 days remaining (and `subscription_cancelled=true` so the
        normal soft-cancel endpoint is a no-op). This admin path
        sidesteps that idempotency check and forcibly rewinds the
        account to the pre-purchase state.

        Returns the refreshed UserDTO so the caller can verify the
        attributes were applied without an extra round-trip.
        """
        keycloak_user = self.identity_provider.get(KeycloakUserQueryDTO(id=user_id))
        # Pass empty list `[]` rather than None for the cleared
        # attributes — Keycloak interprets `[]` as "remove this
        # attribute", while None means "leave it alone" in our
        # KeycloakUserUpdateDTO contract (see converters.py:204
        # comment for the same convention on subscription_cancelled).
        attrs = KeycloakAttributesUpdateDTO(
            plan=[PlanType.FREE.value],
            subscription_end=[],
            subscription_cancelled=[],
        )
        self.identity_provider.update_user(
            user_id,
            KeycloakUserUpdateDTO(
                email=keycloak_user.email,
                attributes=attrs,
            ),
        )
        logger.info(
            "Subscription forcibly reset to FREE for user %s "
            "(admin path, used for App Store reviewer demo prep)",
            user_id,
        )
        return self.get_user(user_id)

    def grant_pro_subscription(self, user_id: UUID, days: int = 30) -> UserDTO:
        """Grant or extend a PRO subscription by `days` days.

        Smart semantics — automatically picks grant vs extend based on
        the user's current state:
          - User has no active PRO (FREE or expired) → start from `now`.
            New `subscription_end` = now + days.
          - User has active PRO with future `subscription_end` → extend.
            New `subscription_end` = current_end + days (adds to the
            remaining time instead of resetting).

        Mirrors the natural admin intent ("give them N more days")
        without forcing the caller to decide grant-vs-extend. Operator
        wanting to truncate a long subscription should reset to FREE
        first, then grant N days.

        Sets:
          - plan → "PRO"
          - subscription_end → calculated as above, ISO format
          - subscription_cancelled → cleared (empty list)

        Empty-list semantics for attrs mirror `reset_subscription`:
        `[]` means "remove this attribute" in our KeycloakAttributesUpdateDTO.
        """
        if days < 1:
            raise ValueError(f"days must be >= 1 (got {days})")
        keycloak_user = self.identity_provider.get(KeycloakUserQueryDTO(id=user_id))
        # Read current subscription state so we can decide whether to
        # grant fresh (from now) or extend (from current_end).
        current = self.get_user(user_id)
        now_utc = datetime.now(UTC)
        base_end = now_utc
        if current.subscription_end:
            existing = current.subscription_end
            if existing.tzinfo is None:
                existing = existing.replace(tzinfo=UTC)
            # Only extend from existing_end if it's still in the future
            # — an expired subscription_end shouldn't anchor a backdated
            # extension (would compress the granted window).
            if existing > now_utc:
                base_end = existing
        new_end = base_end + timedelta(days=days)
        end_iso = new_end.isoformat()
        attrs = KeycloakAttributesUpdateDTO(
            plan=[PlanType.PRO.value],
            subscription_end=[end_iso],
            subscription_cancelled=[],
        )
        self.identity_provider.update_user(
            user_id,
            KeycloakUserUpdateDTO(
                email=keycloak_user.email,
                attributes=attrs,
            ),
        )
        was_extend = base_end != now_utc
        logger.info(
            "PRO subscription %s (admin path) for user %s: %+d days, "
            "ends %s",
            "extended" if was_extend else "granted",
            user_id, days, end_iso,
        )
        return self.get_user(user_id)

    def adjust_points(
        self,
        user_id: UUID,
        mode: str,
        value: int,
        reason: str | None = None,
    ) -> dict:
        """Manually adjust a user's leaderboard points (user_points.total_points).

        mode="delta" → add `value` (may be negative) to the current total.
        mode="set"   → set the total to exactly `value` (must be >= 0); the
                       applied delta is derived as value - current so the
                       PointsAuditLog before/after stays accurate.

        Every change goes through UserPointsRepository.add_points, which writes
        a PointsAuditLog row (source_type="admin_adjustment"). The total is
        floored at 0 — negative leaderboard standings are nonsensical, so a
        delta that would underflow is clamped to -current and the actually
        applied delta is reported back.

        Caller is responsible for cache invalidation
        (`user_points` resource for this user) — see the route.
        """
        if self._session is None:
            raise RuntimeError("DB session is required to adjust points")
        if mode not in ("delta", "set"):
            raise ValueError(f"unknown mode {mode!r} (expected 'delta' or 'set')")
        if mode == "set" and value < 0:
            raise ValueError("value must be >= 0 in 'set' mode")

        repo = UserPointsRepository(self._session)
        current = repo.get_total_points(user_id)
        delta = (value - current) if mode == "set" else value
        # Floor the resulting total at 0.
        if current + delta < 0:
            delta = -current

        if delta != 0:
            repo.add_points(
                user_id,
                delta,
                source_type="admin_adjustment",
                reason=reason or "Manual admin adjustment",
            )
            self._session.commit()

        new_total = repo.get_total_points(user_id)
        new_rank = repo.get_user_rank(user_id)
        logger.info(
            "Admin adjusted points for user %s: mode=%s value=%d applied_delta=%+d "
            "→ total=%d rank=%d (reason=%r)",
            user_id, mode, value, delta, new_total, new_rank, reason,
        )
        return {
            "user_id": str(user_id),
            "total_points": new_total,
            "rank": new_rank,
            "applied_delta": delta,
        }
