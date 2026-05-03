from uuid import UUID

from api.routes.auth.dtos import (
    AuthConfirmRegistrationParamsDTO,
    CodeCheckDTO,
    CodeRequestDTO,
    LoginParamsDTO,
    PasswordResetCompleteDTO,
    RegisterParamsDTO,
    RegistrationCompleteDTO,
)
from auth.dtos import (
    ConfirmationCodeAction,
)
from auth.dtos.auth import AuthConfirmationCodeDTO, AuthLoginDTO, AuthRegisterDTO
from clients.notification import CodePlatform


def to_auth_register_dto(params: RegisterParamsDTO) -> AuthRegisterDTO:
    return AuthRegisterDTO(
        name=params.name,
        phone=params.phone,
        email=params.email,
        password=params.password,
        platform=params.platform,
    )


def to_auth_login_dto(params: LoginParamsDTO) -> AuthLoginDTO:
    return AuthLoginDTO(login=params.login, password=params.password)


def to_auth_confirmation_code_dto(
    params: AuthConfirmRegistrationParamsDTO,
) -> AuthConfirmationCodeDTO:
    return AuthConfirmationCodeDTO(registration_id=params.registration_id, code=params.code)


def to_code_request_dto(contact: str, platform: CodePlatform, action: ConfirmationCodeAction) -> CodeRequestDTO:
    return CodeRequestDTO(
        contact=contact,
        platform=platform,
        action=action,
    )


def to_code_check_dto(verification_id: UUID, code: int, action: ConfirmationCodeAction) -> CodeCheckDTO:
    return CodeCheckDTO(
        verification_id=verification_id,
        code=code,
        action=action,
    )


def to_registration_complete_dto(verification_id: UUID, password: str, name: str) -> RegistrationCompleteDTO:
    return RegistrationCompleteDTO(
        verification_id=verification_id,
        password=password,
        name=name,
    )


def to_password_reset_complete_dto(verification_id: UUID, new_password: str) -> PasswordResetCompleteDTO:
    return PasswordResetCompleteDTO(
        verification_id=verification_id,
        new_password=new_password,
    )
