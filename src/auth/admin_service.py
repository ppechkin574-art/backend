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
