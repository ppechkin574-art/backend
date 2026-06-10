import json
import logging
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from redis import Redis

from api.dependencies import (
    get_app_settings_service,
    get_auth_service,
    get_file_service,
    get_notification_client_email,
    get_redis,
    get_user,
)
from api.middlewares.rate_limit import limiter
from api.middlewares.sms_quota import check_sms_quota, record_sms_request
from app_config.service import AppSettingsService
from clients.notification.client import NotificationClientEmail
from api.routes.auth.converters import to_auth_login_dto
from api.routes.auth.dtos import (
    ChangePasswordDTO,
    CodeCheckDTO,
    CodeCheckResponse,
    CodeRequestDTO,
    CodeRequestResponse,
    ConfirmationDTO,
    ContactChangeConfirmRequest,
    ContactChangeRequest,
    LoginParamsDTO,
    LogoutParamsDTO,
    OAuthCallbackResponse,
    OAuthStartResponse,
    PasswordResetCompleteDTO,
    RefreshTokenParamsDTO,
    RegistrationCompleteDTO,
    TokensDTO,
)
from api.routes.auth.responses import (
    change_password_responses,
    contact_change_confirm_responses,
    contact_change_request_responses,
    delete_account_responses,
    login_responses,
    logout_responses,
    oauth_callback_responses,
    profile_get_responses,
    profile_put_responses,
    refresh_responses,
    registration_complete_responses,
)
from auth.dtos.auth import (
    AuthLoginDTO,
    AuthSessionDTO,
    OAuthProviders,
)
from auth.dtos.users import UserDTO, UserUpdateDTO
from auth.exceptions import (
    AuthBadCredentialsError,
    AuthConfirmationCodeExpiredError,
    AuthFailedConfirmationError,
    AuthInvalidConfirmationCodeError,
    AuthInvalidRefreshTokenError,
    AuthNotVerifiedError,
    AuthUserEmailExistsError,
    AuthUserExistsError,
    AuthUserNotFoundError,
    AuthUserPhoneExistsError,
)
from auth.services import AuthService, AuthServiceInterface
from utils.file_service import FileService
from utils.monitoring import log_error, log_info, log_warning

logger = logging.getLogger(__name__)

public_router = APIRouter()
protected_router = APIRouter()


def perform_login(
    params: AuthLoginDTO, service: AuthServiceInterface
) -> AuthSessionDTO:
    try:
        tokens = service.login(params)
        log_info(
            "User logged in successfully",
            user_id=params.login,
            action="login",
            auth_method="password",
        )
    except AuthBadCredentialsError as e:
        log_warning(
            "Bad credentials provided",
            user_id=params.login,
            action="login",
            auth_method="password",
            error_type="AuthBadCredentialsError",
        )
        raise e
    except AuthNotVerifiedError as e:
        log_warning(
            "User not verified attempted login",
            user_id=params.login,
            action="login",
            auth_method="password",
            error_type="AuthNotVerifiedError",
        )
        raise e

    return tokens


@public_router.post(
    "/login-swagger", response_model=TokensDTO, responses=login_responses
)
def swagger_login(
    username: str = Form(),
    password: str = Form(),
    service: AuthServiceInterface = Depends(get_auth_service),
):
    """Login via Swagger UI"""
    log_info(
        "Swagger login request",
        user_id=username,
        action="login",
        auth_method="password",
    )
    params = AuthLoginDTO(login=username, password=password)
    return perform_login(params, service)


# Two-layer rate limit:
#   * 1/minute  — short-burst protection. Anyone who hits "Resend code" twice
#     in a minute gets bounced. Lives in slowapi's per-IP bucket.
#   * 10/hour   — daily cap. Even if an attacker spaces requests out to
#     bypass the per-minute limit, a single IP can't drain more than ~10
#     SMS units of SMSC budget per hour. Combined with the per-contact
#     60-second Redis block in AuthService, that bounds the worst case
#     to ~10 SMS per hour per IP regardless of phone-number rotation.
@public_router.post("/code/request", response_model=CodeRequestResponse)
@limiter.limit("10/hour")
@limiter.limit("1/minute")
async def request_code(
    request: Request,
    request_data: CodeRequestDTO,
    service: AuthService = Depends(get_auth_service),
    redis: Redis = Depends(get_redis),
    app_settings: AppSettingsService = Depends(get_app_settings_service),
    email_client: NotificationClientEmail = Depends(get_notification_client_email),
):
    """Universal endpoint for requesting confirmation codes"""
    log_info(
        "Code request",
        user_id="anonymous",
        action="request_code",
        auth_method="code",
        contact=request_data.contact,
        platform=request_data.platform.value,
        action_type=request_data.action.value,
    )

    # SMS-abuse defence layer 1+2: global daily cap + per-IP daily block.
    # Reviewer-bypass contacts are skipped inside check_sms_quota so Apple
    # App Review keeps working even if everyone else is locked out.
    # Raises HTTPException with the appropriate status if either limit hits.
    check_sms_quota(request, request_data.contact, redis, app_settings)

    try:
        verification_id, channel_used = service.request_code(
            request_data.contact, request_data.platform, request_data.action
        )

        # Count this request toward both daily counters. Done AFTER the
        # service call so Pydantic / KZ-phone / user-exists rejections
        # don't inflate the per-IP block counter (those are 4xx errors,
        # not abuse signals).
        record_sms_request(request, request_data.contact, redis, app_settings, email_client)

        log_info(
            "Code requested successfully",
            user_id="anonymous",
            action="request_code",
            auth_method="code",
            verification_id=str(verification_id),
            delivery_channel=channel_used or "none",
        )

        # If every primary channel failed AND the Telegram bot is
        # configured, include the deep link so the client can render the
        # "Открыть Telegram" fallback modal. Empty bot_username (= bot not
        # configured) → field stays null → client falls back to the
        # generic "Не удалось отправить" snackbar as before.
        tg_fallback_url: str | None = None
        if channel_used is None:
            container = request.app.state.container
            tg_settings = container.config().telegram_otp
            if tg_settings.bot_username and tg_settings.bot_token:
                # Telegram deep-link format: https://t.me/<bot>?start=<payload>
                # The payload is passed verbatim to the bot's /start handler
                # via the message text (see routes.py:telegram_webhook).
                tg_fallback_url = (
                    f"https://t.me/{tg_settings.bot_username}?start={verification_id}"
                )

        return CodeRequestResponse(
            verification_id=verification_id,
            delivery_channel=channel_used,
            telegram_fallback_url=tg_fallback_url,
        )

    except ValueError as e:
        log_warning(
            "Invalid contact format",
            user_id="anonymous",
            action="request_code",
            auth_method="code",
            contact=request_data.contact,
            error_type="ValidationError",
            error_message=str(e),
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except AuthUserExistsError as e:
        log_warning(
            "User already exists",
            user_id="anonymous",
            action="request_code",
            auth_method="code",
            contact=request_data.contact,
            error_type="AuthUserExistsError",
            error_message=str(e),
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        log_error(
            "Code request failed",
            user_id="anonymous",
            action="request_code",
            auth_method="code",
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не удалось отправить код. Попробуйте позже.",
        )


@public_router.post("/code/check", response_model=CodeCheckResponse)
@limiter.limit("10/minute")
async def check_code(
    request: Request,
    request_data: CodeCheckDTO,
    service: AuthService = Depends(get_auth_service),
):
    """Universal endpoint for checking confirmation codes"""
    log_info(
        "Code check request",
        user_id="anonymous",
        action="check_code",
        auth_method="code",
        verification_id=str(request_data.verification_id),
        action_type=request_data.action.value,
    )

    is_valid = service.check_code(
        request_data.verification_id, request_data.code, request_data.action
    )

    if is_valid:
        log_info(
            "Code verified successfully",
            user_id="anonymous",
            action="check_code",
            auth_method="code",
            verification_id=str(request_data.verification_id),
        )
    else:
        log_warning(
            "Code verification failed",
            user_id="anonymous",
            action="check_code",
            auth_method="code",
            verification_id=str(request_data.verification_id),
        )

    return CodeCheckResponse(valid=is_valid)


@public_router.post(
    "/registration/complete",
    response_model=TokensDTO,
    responses=registration_complete_responses,
)
async def registration_complete(
    request_data: RegistrationCompleteDTO,
    service: AuthService = Depends(get_auth_service),
):
    """Complete registration after code verification"""
    log_info(
        "Registration completion request",
        user_id="anonymous",
        action="registration_complete",
        auth_method="code",
        verification_id=str(request_data.verification_id),
    )

    try:
        tokens = service.complete_registration(
            request_data.verification_id, request_data.password, request_data.name
        )

        log_info(
            "Registration completed successfully",
            user_id=tokens.user_id if hasattr(tokens, "user_id") else "unknown",
            action="registration_complete",
            auth_method="code",
            verification_id=str(request_data.verification_id),
        )

        return tokens

    except (
        AuthInvalidConfirmationCodeError,
        AuthConfirmationCodeExpiredError,
        AuthFailedConfirmationError,
        AuthUserExistsError,
    ) as e:
        log_warning(
            "Registration completion failed",
            user_id="anonymous",
            action="registration_complete",
            auth_method="code",
            verification_id=str(request_data.verification_id),
            error_type=type(e).__name__,
        )
        raise e


@public_router.post("/password-reset/complete", response_model=TokensDTO)
@limiter.limit("5/minute")
async def password_reset_complete(
    request: Request,
    request_data: PasswordResetCompleteDTO,
    service: AuthService = Depends(get_auth_service),
):
    """Complete password reset after code verification.

    Returns fresh tokens (same shape as /login) so the mobile client can
    auto-login without a follow-up call. All existing sessions for the
    user are revoked as a side effect.
    """
    log_info(
        "Password reset completion request",
        user_id="anonymous",
        action="password_reset_complete",
        auth_method="code",
        verification_id=str(request_data.verification_id),
    )

    try:
        tokens = service.complete_password_reset(
            request_data.verification_id, request_data.new_password
        )

        log_info(
            "Password reset completed successfully",
            user_id="anonymous",
            action="password_reset_complete",
            auth_method="code",
            verification_id=str(request_data.verification_id),
        )

        return tokens

    except (
        AuthInvalidConfirmationCodeError,
        AuthConfirmationCodeExpiredError,
        AuthFailedConfirmationError,
    ) as e:
        log_warning(
            "Password reset completion failed",
            user_id="anonymous",
            action="password_reset_complete",
            auth_method="code",
            verification_id=str(request_data.verification_id),
            error_type=type(e).__name__,
        )
        raise e


@public_router.get(
    "/oauth/{provider}", summary="Start OAuth flow", response_model=OAuthStartResponse
)
async def oauth_start(
    provider: OAuthProviders,
    next: str | None = Query(None),
    redis: Redis = Depends(get_redis),
    auth_service: AuthService = Depends(get_auth_service),
):
    """Start OAuth authentication flow"""
    try:
        state = uuid.uuid4().hex
        redirect_after_auth = next or auth_service.oauth_helper.get_frontend_redirect(
            provider
        )

        state_data = {"provider": provider, "redirect_url": redirect_after_auth}

        redis.setex(f"oauth:state:{state}", 300, json.dumps(state_data))

        auth_url = auth_service.oauth_helper.get_authorization_url(provider, state)

        log_info(
            "OAuth flow started",
            user_id="anonymous",
            action="oauth_start",
            auth_method="oauth",
            provider=provider,
            state=state,
        )

        return OAuthStartResponse(
            oauth_url=auth_url,
            state=state,
            redirect_after_auth=redirect_after_auth,
            expires_in=300,
        )

    except ValueError as e:
        log_warning(
            "Unsupported OAuth provider",
            user_id="anonymous",
            action="oauth_start",
            auth_method="oauth",
            provider=provider,
            error_type="ValueError",
            error_message=str(e),
        )
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log_error(
            "OAuth start failed",
            user_id="anonymous",
            action="oauth_start",
            auth_method="oauth",
            provider=provider,
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise HTTPException(status_code=400, detail=str(e))


@public_router.get(
    "/oauth/{provider}/callback",
    response_model=OAuthCallbackResponse,
    responses=oauth_callback_responses,
)
@public_router.post(
    "/oauth/{provider}/callback",
    response_model=OAuthCallbackResponse,
    responses=oauth_callback_responses,
)
@limiter.limit("10/minute")
async def oauth_callback(
    provider: OAuthProviders,
    request: Request,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    auth_service: AuthService = Depends(get_auth_service),
    redis: Redis = Depends(get_redis),
):
    """OAuth callback endpoint"""
    try:
        log_info(
            "OAuth callback received",
            user_id="anonymous",
            action="oauth_callback",
            auth_method="oauth",
            provider=provider,
            method=request.method,
            query_params=dict(request.query_params),
        )

        if error:
            log_warning(
                "OAuth callback error",
                user_id="anonymous",
                action="oauth_callback",
                auth_method="oauth",
                provider=provider,
                error_type="OAuthError",
                error_message=error,
            )
            raise HTTPException(status_code=400, detail=f"OAuth error: {error}")

        if request.method == "POST":
            form_data = await request.form()
            code = form_data.get("code", code)
            state = form_data.get("state", state)
            log_info(
                "Extracted form data from POST",
                user_id="anonymous",
                action="oauth_callback",
                auth_method="oauth",
                provider=provider,
                state=state,
            )

        if not code:
            log_warning(
                "OAuth callback missing code parameter",
                user_id="anonymous",
                action="oauth_callback",
                auth_method="oauth",
                provider=provider,
                method=request.method,
            )
            raise HTTPException(status_code=400, detail="Missing code parameter")

        if not state:
            log_warning(
                "OAuth callback missing state parameter",
                user_id="anonymous",
                action="oauth_callback",
                auth_method="oauth",
                provider=provider,
                method=request.method,
            )
            raise HTTPException(status_code=400, detail="Missing state parameter")

        key = f"oauth:state:{state}"
        state_data_str = redis.get(key)
        if not state_data_str:
            log_warning(
                "OAuth callback invalid state",
                user_id="anonymous",
                action="oauth_callback",
                auth_method="oauth",
                provider=provider,
                state=state,

                error_type="InvalidState",
            )
            raise HTTPException(status_code=400, detail="Invalid or expired state")

        redis.delete(key)

        state_data = json.loads(
            state_data_str.decode()
            if isinstance(state_data_str, bytes)
            else state_data_str
        )

        stored_provider = state_data.get("provider")
        frontend = state_data.get("redirect_url")

        if stored_provider != provider:
            log_warning(
                "OAuth state provider mismatch",
                user_id="anonymous",
                action="oauth_callback",
                auth_method="oauth",
                stored_provider=stored_provider,
                requested_provider=provider,
                error_type="ProviderMismatch",
            )
            raise HTTPException(status_code=400, detail="State provider mismatch")

        tokens = auth_service.login_via_oauth(code, provider)

        log_info(
            "OAuth login successful",
            user_id=tokens.user_id if hasattr(tokens, "user_id") else "unknown",
            action="oauth_callback",
            auth_method="oauth",
            provider=provider,
        )

        return OAuthCallbackResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            redirect_url=frontend,
            provider=provider,
        )

    except HTTPException:
        raise
    except Exception as e:
        log_error(
            "OAuth callback failed",
            user_id="anonymous",
            action="oauth_callback",
            auth_method="oauth",
            provider=provider,
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise HTTPException(status_code=400, detail=str(e))


@public_router.post(
    "/refresh-token", response_model=TokensDTO, responses=refresh_responses
)
def refresh_token(
    refresh_params: RefreshTokenParamsDTO,
    service: AuthServiceInterface = Depends(get_auth_service),
):
    """Refresh access token"""
    log_info(
        "Refresh token request",
        user_id="unknown",
        action="refresh_token",
        auth_method="token",
    )
    try:
        tokens = service.refresh_token(refresh_params.refresh_token)
        log_info(
            "Token refreshed successfully",
            user_id=tokens.user_id if hasattr(tokens, "user_id") else "unknown",
            action="refresh_token",
            auth_method="token",
        )
    except AuthInvalidRefreshTokenError as e:
        log_warning(
            "Invalid refresh token",
            user_id="unknown",
            action="refresh_token",
            auth_method="token",
            error_type="AuthInvalidRefreshTokenError",
        )
        raise e

    return tokens


@public_router.post("/login", response_model=TokensDTO, responses=login_responses)
@limiter.limit("5/minute")
def login(
    request: Request,
    login_params: LoginParamsDTO,
    service: AuthServiceInterface = Depends(get_auth_service),
):
    """Authenticate user with credentials"""
    log_info(
        "Login request",
        user_id=login_params.login,
        action="login",
        auth_method="password",
    )
    params = to_auth_login_dto(login_params)
    return perform_login(params, service)


@protected_router.get(
    "/profile",
    response_model=UserDTO,
    responses=profile_get_responses,
    response_model_exclude={"roles"},
)
def get_current_user(
    user: UserDTO = Depends(get_user),
    file_service: FileService = Depends(get_file_service),
):
    """Get current user profile"""
    log_info(
        "Profile request",
        user_id=user.id,
        action="get_profile",
        auth_method="token",
    )
    # Always generate a fresh presigned URL — stored value may be an expired
    # legacy URL or just a bare filename depending on when avatar was uploaded.
    avatar_url = file_service.get_avatar_url(user.avatar) if user.avatar else None
    return user.model_copy(update={"avatar": avatar_url or None})


@protected_router.patch(
    "/profile", response_model=UserDTO, responses=profile_put_responses
)
@limiter.limit("10/hour")
async def update_current_user(
    request: Request,
    name: str | None = Form(None),
    email: str | None = Form(None),
    phone: str | None = Form(None),
    avatar: UploadFile | None = File(None),
    avatar_action: str | None = Form(None),
    user: UserDTO = Depends(get_user),
    service: AuthServiceInterface = Depends(get_auth_service),
    file_service: FileService = Depends(get_file_service),
):
    """Update user profile information"""
    log_info(
        "Profile update request",
        user_id=user.id,
        action="update_profile",
        auth_method="token",
        avatar_action=avatar_action,
    )

    try:
        VALID_AVATAR_ACTIONS = {"delete", "update"}

        if avatar and avatar.filename and avatar_action != "update":
            raise HTTPException(
                status_code=400,
                detail="When avatar file is provided, avatar_action must be 'update'",
            )

        if avatar_action == "update" and (not avatar or not avatar.filename):
            raise HTTPException(
                status_code=400,
                detail="When avatar_action='update', avatar file is required",
            )

        if avatar_action == "delete" and avatar and avatar.filename:
            raise HTTPException(
                status_code=400,
                detail="When avatar_action='delete', avatar file should not be provided",
            )

        if avatar_action and avatar_action not in VALID_AVATAR_ACTIONS:
            raise HTTPException(
                status_code=400,
                detail=f"avatar_action must be one of: {', '.join(VALID_AVATAR_ACTIONS)}",
            )

        if email is not None:
            raise HTTPException(
                status_code=400,
                detail="Use endpoint '/contact/change-request' to edit email",
            )

        if phone is not None:
            raise HTTPException(
                status_code=400,
                detail="Use endpoint '/contact/change-request' to edit phone",
            )

        avatar_url = None

        if avatar_action == "delete":
            log_info("Deleting avatar", user_id=user.id)
            if user.avatar:
                old_filename = user.avatar.split("/")[-1]
                file_service.delete_avatar(old_filename)
            avatar_url = None

        elif avatar_action == "update":
            log_info("Updating avatar", user_id=user.id, filename=avatar.filename)
            filename = await file_service.save_avatar(str(user.id), avatar)
            # Store bare filename in Keycloak — presigned URLs expire and must
            # be generated fresh on each profile/leaderboard request.
            avatar_url = filename

            if user.avatar:
                file_service.delete_avatar(user.avatar)

        update_dict = {}
        if name is not None:
            update_dict["name"] = name

        if avatar_action in ["delete", "update"]:
            update_dict["avatar"] = avatar_url

        updated_user = service.update_user_profile(user, UserUpdateDTO(**update_dict))

        # Return fresh presigned URL (updated_user.avatar is now a bare filename)
        resolved = file_service.get_avatar_url(updated_user.avatar) if updated_user.avatar else None
        return updated_user.model_copy(update={"avatar": resolved or None})

    except (AuthUserEmailExistsError, AuthUserPhoneExistsError) as e:
        log_warning(
            "Profile update failed - conflict",
            user_id=user.id,
            action="update_profile",
            auth_method="token",
            error_type=type(e).__name__,
            field="email" if isinstance(e, AuthUserEmailExistsError) else "phone",
        )
        raise e

    except HTTPException:
        raise

    except Exception as e:
        log_error(
            "Unexpected error in profile update",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@protected_router.post(
    "/change-password", status_code=204, responses=change_password_responses
)
def change_password(
    request_data: ChangePasswordDTO,
    user: UserDTO = Depends(get_user),
    service: AuthService = Depends(get_auth_service),
):
    """Change password for authenticated user"""
    log_info(
        "Change password request",
        user_id=user.id,
        action="change_password",
        auth_method="password",
    )

    try:
        service.change_password(
            user.id, request_data.old_password, request_data.new_password
        )

        log_info(
            "Password changed successfully",
            user_id=user.id,
            action="change_password",
            auth_method="password",
        )

        return Response(status_code=status.HTTP_204_NO_CONTENT)

    except AuthBadCredentialsError:
        log_warning(
            "Wrong old password provided",
            user_id=user.id,
            action="change_password",
            auth_method="password",
            error_type="AuthBadCredentialsError",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid current password"
        )
    except AuthUserNotFoundError as e:
        log_warning(
            "User not found during password change",
            user_id=user.id,
            action="change_password",
            auth_method="password",
            error_type="AuthUserNotFoundError",
        )
        raise e
    except Exception as e:
        log_error(
            "Password change failed",
            user_id=user.id,
            action="change_password",
            auth_method="password",
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@protected_router.post(
    "/contact/change-request",
    status_code=200,
    response_model=ConfirmationDTO,
    summary="Request verification code for contact change",
    responses=contact_change_request_responses,
)
async def contact_change_request(
    data: ContactChangeRequest,
    user: UserDTO = Depends(get_user),
    auth_service: AuthServiceInterface = Depends(get_auth_service),
):
    """Request verification code to change email or phone"""
    verification_id = auth_service.change_contact_request(
        user_id=user.id,
        contact=data.contact,
        platform=data.platform,
    )
    return ConfirmationDTO(verification_id=verification_id)


@protected_router.post(
    "/contact/change-confirm",
    status_code=200,
    response_model=UserDTO,
    summary="Confirm contact change with verification code",
    responses=contact_change_confirm_responses,
)
@limiter.limit("5/minute")
async def contact_change_confirm(
    request: Request,
    data: ContactChangeConfirmRequest,
    _user: UserDTO = Depends(get_user),
    auth_service: AuthServiceInterface = Depends(get_auth_service),
):
    """Confirm email or phone change with verification code"""
    updated_user = auth_service.change_contact_confirm(
        verification_id=data.verification_id,
        code=data.code,
    )
    return updated_user


@protected_router.post("/logout", responses=logout_responses, status_code=204)
def logout(
    logout_params: LogoutParamsDTO,
    service: AuthServiceInterface = Depends(get_auth_service),
):
    """Logout user (invalidate refresh token)"""
    log_info(
        "Logout request",
        action="logout",
        auth_method="token",
    )
    try:
        service.logout(logout_params.refresh_token)
        log_info(
            "Logout successful",
            action="logout",
            auth_method="token",
        )
    except AuthInvalidRefreshTokenError:
        log_warning(
            "Logout failed - invalid refresh token",
            action="logout",
            auth_method="token",
            error_type="AuthInvalidRefreshTokenError",
        )
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@protected_router.delete("/delete", status_code=204, responses=delete_account_responses)
def delete_account(
    user: UserDTO = Depends(get_user),
    service: AuthServiceInterface = Depends(get_auth_service),
    file_service: FileService = Depends(get_file_service),
):
    """Delete user account"""
    log_info(
        "Delete account request",
        user_id=user.id,
        action="delete_account",
        auth_method="token",
    )
    try:
        if user.avatar:
            filename = user.avatar.split("/")[-1]
            file_service.delete_avatar(filename)
            log_info(
                f"Deleted avatar during account deletion: {filename}",
                user_id=user.id,
                action="delete_account",
                auth_method="token",
            )
        service.delete_account(user)
        log_info(
            "Account deleted successfully",
            user_id=user.id,
            action="delete_account",
            auth_method="token",
        )
    except AuthUserNotFoundError as e:
        log_warning(
            "Account deletion failed - user not found",
            user_id=user.id,
            action="delete_account",
            auth_method="token",
            error_type="AuthUserNotFoundError",
        )
        raise e

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Telegram-bot webhook for OTP delivery (self-hosted WhatsApp alternative).
# Telegram POSTs an update here whenever the bot receives a message.
# We act only on /start <verification_id> payloads — that's what links the
# user's chat_id to their phone so subsequent OTPs can be delivered to DM
# directly (see services.py:_try_telegram_otp / link_telegram_chat).
#
# Auth: Telegram sends the secret we provided at setWebhook back in the
# `X-Telegram-Bot-Api-Secret-Token` header. A request without it or with
# a mismatched value is dropped. The endpoint also returns 200 even on
# logical no-op (unknown vid, non-/start text) so Telegram doesn't retry
# pointlessly.
# ---------------------------------------------------------------------------
@public_router.post("/telegram/webhook", include_in_schema=False)
async def telegram_webhook(
    request: Request,
    service: AuthService = Depends(get_auth_service),
):
    from dependency_injector.wiring import Provide, inject
    from api.containers import Container

    # Pull TelegramOtpClient out of the DI container manually — the
    # @inject decorator pattern doesn't compose cleanly with the public
    # Telegram webhook signature (extra args confuse FastAPI's body parser).
    container: Container = request.app.state.container
    tg_client = container.telegram_otp_client()
    tg_settings = container.config().telegram_otp

    # 1. Verify secret. Telegram caches setWebhook(secret) and replays
    #    the value back on every POST. Missing/mismatched = drop quietly.
    if tg_settings.webhook_secret:
        provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not _constant_time_eq(provided, tg_settings.webhook_secret):
            log_warning(
                "Telegram webhook secret mismatch — dropping update",
                user_id="anonymous",
                action="telegram_webhook",
            )
            # 200 (not 401) so Telegram doesn't retry, but the log captures it.
            return {"ok": True, "ignored": "secret_mismatch"}

    try:
        update = await request.json()
    except Exception as e:
        logger.warning("Telegram webhook: malformed JSON: %s", e)
        return {"ok": True, "ignored": "bad_json"}

    message = update.get("message") if isinstance(update, dict) else None
    if not message:
        # Other update types (edited_message, callback_query, etc.) — ignore.
        return {"ok": True, "ignored": "no_message"}

    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return {"ok": True, "ignored": "no_chat_id"}

    # /start with optional payload: "/start abc-vid-1234". Without the
    # payload — just greet the user; no OTP context to act on.
    if not text.startswith("/start"):
        # The bot doesn't run a conversational interface; ignore everything
        # else so users get no misleading auto-reply.
        return {"ok": True, "ignored": "not_start"}

    parts = text.split(maxsplit=1)
    payload = parts[1].strip() if len(parts) == 2 else ""
    if not payload:
        # Plain /start. Send a one-time hint so the user understands they
        # need to come from the AIMA app's deep link.
        import contextlib

        with contextlib.suppress(Exception):
            tg_client.send_otp(
                chat_id,
                "_open the AIMA app and tap «Получить код в Telegram»_",
            )
        return {"ok": True, "ignored": "empty_payload"}

    try:
        verification_id = uuid.UUID(payload)
    except ValueError:
        logger.warning("Telegram /start payload not a UUID: %s", payload[:50])
        return {"ok": True, "ignored": "bad_payload"}

    delivered, code = service.link_telegram_chat(verification_id, int(chat_id))
    if not delivered or code is None:
        # The vid expired or was never stashed. Reply with a soft hint so
        # the user knows to retry from the app — silent failure here would
        # look like the bot is broken.
        import contextlib

        with contextlib.suppress(Exception):
            tg_client.send_otp(
                chat_id,
                "Код не найден или истёк. Запросите новый в приложении.",
            )
        return {"ok": True, "ignored": "vid_not_found"}

    try:
        tg_client.send_otp(chat_id, code)
        log_info(
            "OTP delivered via Telegram bot",
            user_id="anonymous",
            action="telegram_webhook",
            verification_id=str(verification_id),
        )
    except Exception as e:
        log_error(
            "Telegram bot send_otp failed after link",
            user_id="anonymous",
            action="telegram_webhook",
            verification_id=str(verification_id),
            error_message=str(e),
        )
        # Still 200 — we don't want Telegram to keep retrying; the user
        # will request a fresh code from the app.
        return {"ok": True, "ignored": "send_failed"}

    return {"ok": True}


def _constant_time_eq(a: str, b: str) -> bool:
    """Constant-time string compare to defeat timing-attacks on the
    webhook secret. The header value is attacker-controlled; without this
    a side-channel could leak the secret one byte at a time.
    """
    import hmac

    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


router = APIRouter(prefix="/auth", tags=["Unified - Auth"])
router.include_router(public_router)
router.include_router(protected_router, dependencies=[Depends(get_user)])
routers = [router]
