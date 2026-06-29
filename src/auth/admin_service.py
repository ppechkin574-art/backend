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
            self._enrich_with_device_info(users)
        return users

    def _enrich_with_pg_stats(self, users: list[UserDTO]) -> None:
        """Batch-fetch streak and points from PostgreSQL and merge into DTOs.

        Two queries for all users at once — no N+1. Users without a row in
        attendance_streaks or students default to 0 (same as the DTO default).
        """
        ids = [str(u.id) for u in users]
        id_list = ", ".join(f"'{uid}'" for uid in ids)

        try:
            streak_rows = self._session.execute(
                text(
                    f"SELECT student_guid, current_streak_days, total_points "
                    f"FROM attendance_streaks WHERE student_guid IN ({id_list})"
                )
            ).fetchall()
            streak_map = {str(r[0]): (r[1], r[2]) for r in streak_rows}

            points_rows = self._session.execute(
                text(f"SELECT user_id, total_points FROM user_points WHERE user_id IN ({id_list})")
            ).fetchall()
            points_map = {str(r[0]): r[1] for r in points_rows}
        except Exception:
            logger.exception("Failed to enrich user list with PG stats — returning defaults")
            return

        for u in users:
            uid = str(u.id)
            if uid in streak_map:
                u.attendance_streak_days = streak_map[uid][0] or 0
                u.attendance_total_points = streak_map[uid][1] or 0
            if uid in points_map:
                u.points = points_map[uid] or 0

    def _enrich_with_device_info(self, users: list[UserDTO]) -> None:
        """Fetch platform list and last_seen from daily_test_device_tokens.

        One query for all users — no N+1. Users without any registered device
        keep their default empty platforms list and None last_seen.
        """
        ids = [str(u.id) for u in users]
        id_list = ", ".join(f"'{uid}'" for uid in ids)
        try:
            rows = self._session.execute(
                text(
                    f"SELECT student_guid, "
                    f"ARRAY_AGG(DISTINCT platform) FILTER (WHERE platform IS NOT NULL) AS platforms, "
                    f"MAX(updated_at) AS last_seen "
                    f"FROM daily_test_device_tokens "
                    f"WHERE student_guid IN ({id_list}) "
                    f"GROUP BY student_guid"
                )
            ).fetchall()
            device_map = {str(r[0]): {"platforms": r[1] or [], "last_seen": r[2]} for r in rows}
        except Exception:
            logger.exception("Failed to enrich user list with device info — returning defaults")
            return

        for u in users:
            uid = str(u.id)
            if uid in device_map:
                u.platforms = device_map[uid]["platforms"]
                u.last_seen = device_map[uid]["last_seen"]

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
