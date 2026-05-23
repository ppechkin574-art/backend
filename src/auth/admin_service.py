import logging
import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

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
    def __init__(self, identity_provider: IdentityProviderClientKeycloak):
        self.identity_provider = identity_provider

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
        return users

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
            plan=PlanType.FREE,
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
        """Forcibly grant a PRO subscription for `days` days.

        Sets:
          - plan → "PRO"
          - subscription_end → now (UTC) + days, ISO format
          - subscription_cancelled → cleared (empty list)

        Used when:
          - IAP receipt failed to propagate (real payment, missing PRO) —
            one-shot grant while the receipt-validation bug is fixed
          - Reviewer / demo accounts need PRO to exercise the gated flows
            during Apple/Google review
          - Comping a user after a support request

        Mirrors `reset_subscription` on attribute semantics — empty list
        means "remove attribute" in our KeycloakAttributesUpdateDTO
        contract.
        """
        if days < 1:
            raise ValueError(f"days must be >= 1 (got {days})")
        keycloak_user = self.identity_provider.get(KeycloakUserQueryDTO(id=user_id))
        end_iso = (datetime.now(UTC) + timedelta(days=days)).isoformat()
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
        logger.info(
            "PRO subscription granted (admin path) to user %s for %d days, "
            "ends %s",
            user_id, days, end_iso,
        )
        return self.get_user(user_id)
