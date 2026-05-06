import logging
import re
import secrets
import string
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from auth.dtos import (
    AuthRegisterDTO,
    AuthSessionDTO,
    ConfirmationCodeCreateDTO,
    RedisConfirmationCodeDTO,
    UserCreateDTO,
    UserDTO,
    UserQueryDTO,
)
from auth.dtos.users import UserTokensDTO, UserUpdateDTO
from clients.identity_provider.dtos import (
    KeycloakAttributesUpdateDTO,
    KeycloakUserUpdateDTO,
)
from common.enums import PlanType

if TYPE_CHECKING:
    from clients.identity_provider import (
        KeycloakAccessTokenDTO,
        KeycloakCreateUserDTO,
        KeycloakUserDTO,
        KeycloakUserQueryDTO,
    )

logger = logging.getLogger(__name__)


def to_user_create_dto(params: AuthRegisterDTO, is_active: bool) -> UserCreateDTO:
    return UserCreateDTO(
        name=params.name,
        phone=params.phone,
        email=params.email,
        password=params.password,
        role="student",
        is_active=is_active,
        plan=PlanType.PRO,
        subscription_end=datetime.now(UTC) + timedelta(days=3),
        used_trial=False,
    )


# def to_confirmation_code_create_dto(
#     user_id: UUID, code: int, expiration: int, action: ConfirmationCodeAction
# ) -> ConfirmationCodeCreateDTO:
#     return ConfirmationCodeCreateDTO(
#         user_id=user_id, code=code, action=action, expiration=expiration
#     )


# def to_confirmation_code_query_dto(
#     user_id: UUID = None, code: int = None, action: ConfirmationCodeAction = None
# ) -> ConfirmationCodeQueryDTO:
#     return ConfirmationCodeQueryDTO(user_id=user_id, code=code, action=action)


def to_user_query_dto(
    user_id: UUID = None, phone: str = None, email: str = None
) -> UserQueryDTO:
    return UserQueryDTO(id=user_id, phone=phone, email=email)


def to_auth_session_dto(tokens: UserTokensDTO) -> AuthSessionDTO:
    return AuthSessionDTO(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
    )


def to_redis_confirmation_code(
    user: ConfirmationCodeCreateDTO,
) -> RedisConfirmationCodeDTO:
    redis_id = uuid.uuid4()

    created_at = datetime.now(UTC)
    expires_at = created_at.timestamp() + user.expiration

    redis_user_id = user.registration_id if user.is_temporary else user.user_id
    if redis_user_id is None:
        raise ValueError("Either user_id or registration_id must be provided")

    return RedisConfirmationCodeDTO(
        id=redis_id,
        user_id=redis_user_id,
        contact=user.contact,
        code=user.code,
        action=user.action,
        is_temporary=user.is_temporary,
        created_at=created_at.isoformat(),
        expires_at=expires_at,
        real_user_id=str(user.user_id) if user.user_id else None,
    )


def to_keycloak_create_user_dto(user: UserCreateDTO) -> "KeycloakCreateUserDTO":
    """Конвертирует UserCreateDTO в KeycloakCreateUserDTO"""
    from clients.identity_provider import (
        KeycloakAttributesDTO,
        KeycloakCreateUserDTO,
        KeycloakCredentialDTO,
    )

    username_base = (
        user.email.split("@")[0] if user.email else transliterate_name(user.name)
    )

    if len(username_base) > 30:
        username_base = username_base[:30]

    username_base = re.sub(r"[^a-zA-Z0-9._-]", "_", username_base)

    random_suffix = "".join(
        secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6)
    )
    username = f"{username_base}_{random_suffix}"

    subscription_end = user.subscription_end or datetime.now(UTC) + timedelta(days=3)

    # Phone-only users get a synthetic email so Keycloak User Profile validation passes
    email = user.email
    if not email and user.phone:
        digits = "".join(filter(str.isdigit, user.phone))
        email = f"phone.{digits}@aima.internal"

    return KeycloakCreateUserDTO(
        username=username,
        email=email,
        firstName=user.name or username,
        lastName=username,
        emailVerified=True,
        attributes=KeycloakAttributesDTO(
            name=[user.name],
            phone=[user.phone] if user.phone else [],
            avatar=[user.avatar] if user.avatar else [],
            role=[user.role],
            allowed_subject_ids=[str(sid) for sid in (user.allowed_subject_ids)],
            plan=[user.plan.value],
            subscription_end=[subscription_end.isoformat()],
        ),
        credentials=(
            [KeycloakCredentialDTO(value=user.password)] if user.password else []
        ),
    )


def to_keycloak_user_query_dto(user: UserQueryDTO) -> "KeycloakUserQueryDTO":
    from clients.identity_provider import KeycloakUserQueryDTO

    return KeycloakUserQueryDTO(
        id=user.id,
        phone=user.phone,
        email=user.email,
    )


def to_keycloak_user_update_dto(
    user: UserDTO, updated_user: UserUpdateDTO
) -> KeycloakUserUpdateDTO:
    update_data = updated_user.model_dump(exclude_unset=True)

    attributes_dict = {}

    if "name" in update_data and update_data["name"] is not None:
        attributes_dict["name"] = [update_data["name"]]
    elif user.name:
        attributes_dict["name"] = [user.name]

    if "phone" in update_data and update_data["phone"] is not None:
        attributes_dict["phone"] = [update_data["phone"]]
    elif user.phone:
        attributes_dict["phone"] = [user.phone]

    if "avatar" in update_data:
        if update_data["avatar"] is None:
            attributes_dict["avatar"] = []
        else:
            attributes_dict["avatar"] = [update_data["avatar"]]
    elif user.avatar:
        attributes_dict["avatar"] = [user.avatar]

    if "plan" in update_data and update_data["plan"] is not None:
        attributes_dict["plan"] = [update_data["plan"].value]
    elif user.plan:
        attributes_dict["plan"] = [user.plan.value]

    if (
        "subscription_end" in update_data
        and update_data["subscription_end"] is not None
    ):
        attributes_dict["subscription_end"] = [
            update_data["subscription_end"].isoformat()
        ]
    elif user.subscription_end:
        attributes_dict["subscription_end"] = [user.subscription_end.isoformat()]

    email = update_data.get("email", user.email)

    attributes = (
        KeycloakAttributesUpdateDTO(**attributes_dict) if attributes_dict else None
    )
    return KeycloakUserUpdateDTO(email=email, attributes=attributes)


def to_user_dto(keycloak_user: "KeycloakUserDTO", roles: list[str]) -> UserDTO:
    phone = None
    if keycloak_user.attributes and keycloak_user.attributes.phone:
        phone_list = keycloak_user.attributes.phone
        if phone_list and len(phone_list) > 0:
            phone = phone_list[0]

    name = ""
    if keycloak_user.attributes and keycloak_user.attributes.name:
        name_list = keycloak_user.attributes.name
        if name_list and len(name_list) > 0:
            name = name_list[0]

    avatar = None
    if keycloak_user.attributes and keycloak_user.attributes.avatar:
        avatar_list = keycloak_user.attributes.avatar
        if avatar_list and len(avatar_list) > 0:
            avatar = avatar_list[0]

    plan_str = None
    if keycloak_user.attributes and keycloak_user.attributes.plan:
        plan_list = keycloak_user.attributes.plan
        if plan_list and len(plan_list) > 0:
            plan_str = plan_list[0]

    if plan_str:
        plan = next(
            (pt for pt in PlanType if pt.value.upper() == plan_str.strip().upper()),
            PlanType.FREE,
        )
    else:
        plan = PlanType.FREE

    subscription_end_str = None
    if keycloak_user.attributes and keycloak_user.attributes.subscription_end:
        sub_end_list = keycloak_user.attributes.subscription_end
        if sub_end_list and len(sub_end_list) > 0:
            subscription_end_str = sub_end_list[0]

    try:
        subscription_end = (
            datetime.fromisoformat(subscription_end_str)
            if subscription_end_str
            else datetime.now(UTC)
        )
    except (ValueError, TypeError):
        subscription_end = datetime.now(UTC)

    allowed_subject_ids = []
    if keycloak_user.attributes and keycloak_user.attributes.allowed_subject_ids:
        ids_list = keycloak_user.attributes.allowed_subject_ids
        if ids_list:
            allowed_subject_ids = [
                int(id_str) for id_str in ids_list if id_str.isdigit()
            ]

    return UserDTO(
        id=keycloak_user.id,
        username=keycloak_user.username,
        name=name,
        phone=phone,
        email=keycloak_user.email,
        avatar=avatar,
        is_active=keycloak_user.enabled,
        roles=roles,
        allowed_subject_ids=allowed_subject_ids,
        plan=plan,
        subscription_end=subscription_end,
        created_at=keycloak_user.createdTimestamp,
        updated_at=keycloak_user.createdTimestamp,
    )


def to_user_tokens_dto(token: "KeycloakAccessTokenDTO") -> UserTokensDTO:
    return UserTokensDTO(
        access_token=token.access_token, refresh_token=token.refresh_token
    )


def transliterate_name(name: str) -> str:
    """Транслитерирует кириллицу в латиницу"""
    translit_dict = {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "yo",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
        "А": "A",
        "Б": "B",
        "В": "V",
        "Г": "G",
        "Д": "D",
        "Е": "E",
        "Ё": "Yo",
        "Ж": "Zh",
        "З": "Z",
        "И": "I",
        "Й": "Y",
        "К": "K",
        "Л": "L",
        "М": "M",
        "Н": "N",
        "О": "O",
        "П": "P",
        "Р": "R",
        "С": "S",
        "Т": "T",
        "У": "U",
        "Ф": "F",
        "Х": "H",
        "Ц": "Ts",
        "Ч": "Ch",
        "Ш": "Sh",
        "Щ": "Sch",
        "Ъ": "",
        "Ы": "Y",
        "Ь": "",
        "Э": "E",
        "Ю": "Yu",
        "Я": "Ya",
    }

    result = []
    for char in name:
        result.append(translit_dict.get(char, char))

    return "".join(result)
