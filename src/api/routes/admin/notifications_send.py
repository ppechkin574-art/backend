"""Admin endpoint for sending broadcast push notifications from the
admin panel UI. Lives next to (not replacing) the legacy
`/admin/notifications/test/send` endpoint — that one is hooked to a
'remove in production' note in the code and was wired for ad-hoc
shell testing, not the admin UI.

This endpoint is what the admin frontend's Push-уведомления page
calls when the operator hits 'Send'. It supports a minimal target
filter (all / ios / pro) so a release announcement can hit only PRO
subscribers, a new-iOS-build push can hit only iOS devices, etc.
"""

from __future__ import annotations

import logging
import os
from typing import Literal
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.containers import Container
from api.dependencies import (
    allow_admin_or_marketing,
    get_database,
    get_identity_provider_client_keycloak,
    get_settings,
)
from api.exceptions.documentation import get_common_responses
from clients.firebase import FirebaseNotificationClient
from clients.firebase.settings import FirebaseSettings
from clients.identity_provider.client import IdentityProviderClientKeycloak
from clients.identity_provider.dtos import KeycloakUserQueryDTO
from database import Database
from quiz.models.daily_tests import DailyTestDeviceToken
from quiz.services.admin_broadcast_notifications import (
    AdminBroadcastNotificationService,
    BroadcastTarget,
)
from settings import Settings

# Marketing surface: the Push-уведомления page (POST /admin/notifications/send)
# is part of the marketing toolset, so it is gated by
# `allow_admin_or_marketing` (admins keep access; `marketing`-role users
# also get in). This router only exposes the broadcast /send endpoint.
router = APIRouter(
    prefix="/admin/notifications",
    tags=["Admin - Notifications"],
    dependencies=[Depends(allow_admin_or_marketing)],
)

logger = logging.getLogger(__name__)


class SendNotificationRequestDTO(BaseModel):
    """Body for POST /admin/notifications/send.

    Length caps mirror the platform-side rendering limits: iOS will
    truncate notification titles past ~30 visible chars and bodies
    past ~180 in the lock-screen preview, so anything above 100/500
    is almost certainly a mistake (pasted essay, missing UI clip).
    Title/body content itself isn't validated — admins can use
    Russian, Kazakh, English, emoji etc.
    """

    title: str = Field(..., min_length=1, max_length=100)
    body: str = Field(..., min_length=1, max_length=500)
    target: Literal["all", "pro", "ios"] = Field(
        "all",
        description="all = every device; pro = users on PRO plan; "
        "ios = devices with platform=ios",
    )


class SendNotificationResponseDTO(BaseModel):
    """Send outcome — surfaced to the admin UI so the operator can
    eyeball whether the broadcast actually reached anyone.

    `matched_tokens` is the size of the target slice (after the
    filter); `requested` is what FCM actually attempted (same number
    unless an empty batch was skipped). `failed` includes transient
    FCM errors AND `removed_tokens` (those Firebase reported as
    UNREGISTERED — we already cleaned them up server-side, but they
    do count as a failed delivery for this broadcast)."""

    target: str
    matched_tokens: int
    requested: int
    delivered: int
    failed: int
    removed_tokens: int


@inject
def get_firebase_client(
    firebase_client: FirebaseNotificationClient = Depends(Provide[Container.firebase_client]),
) -> FirebaseNotificationClient:
    return firebase_client


def get_firebase_settings(
    settings: Settings = Depends(get_settings),
) -> FirebaseSettings:
    return settings.firebase


def get_broadcast_service(
    database: Database = Depends(get_database),
    firebase_client: FirebaseNotificationClient = Depends(get_firebase_client),
    firebase_settings: FirebaseSettings = Depends(get_firebase_settings),
    idp: IdentityProviderClientKeycloak = Depends(get_identity_provider_client_keycloak),
) -> AdminBroadcastNotificationService:
    return AdminBroadcastNotificationService(
        database=database,
        firebase_client=firebase_client,
        firebase_settings=firebase_settings,
        identity_provider=idp,
    )


@router.post(
    "/send",
    response_model=SendNotificationResponseDTO,
    summary="Отправить push-уведомление с фильтром аудитории",
    description=(
        "Production-grade broadcast endpoint used by the admin panel. "
        "Pick a target slice (all / pro / ios) and a title+body; the "
        "service fans out to FCM in pages, prunes any UNREGISTERED "
        "tokens it learns about, and returns aggregate counts."
    ),
    responses={**get_common_responses("create")},
)
async def send_admin_broadcast(
    request: SendNotificationRequestDTO,
    service: AdminBroadcastNotificationService = Depends(get_broadcast_service),
):
    logger.info(
        "Admin broadcast push request",
        extra={
            "title_chars": len(request.title),
            "body_chars": len(request.body),
            "target": request.target,
        },
    )

    if not service.enabled:
        # 503 (not 400) because the failure is server-side
        # configuration, not a malformed request from the admin UI.
        raise HTTPException(
            status_code=503,
            detail=(
                "Firebase notifications are disabled. Set firebase__enabled=True "
                "and configure credentials before sending broadcasts."
            ),
        )

    try:
        result = service.send(
            title=request.title,
            body=request.body,
            target=request.target,
        )
    except Exception as exc:
        logger.exception("Admin broadcast push failed")
        raise HTTPException(
            status_code=500,
            detail="Failed to send broadcast",
        ) from exc

    logger.info(
        "Admin broadcast push sent",
        extra={
            "target": result.target,
            "matched": result.matched_tokens,
            "requested": result.requested,
            "delivered": result.delivered,
            "failed": result.failed,
            "removed": result.removed_tokens,
        },
    )

    return SendNotificationResponseDTO(
        target=result.target,
        matched_tokens=result.matched_tokens,
        requested=result.requested,
        delivered=result.delivered,
        failed=result.failed,
        removed_tokens=result.removed_tokens,
    )


# ---------------------------------------------------------------------------
# Test-send: fire a push to the fixed reviewer/dev phone numbers only.
# Used to preview how a notification looks before broadcasting to all users.
# ---------------------------------------------------------------------------

def _get_test_phones() -> list[str]:
    """Return deduplicated list of phone numbers from REVIEWER_TEST_PHONE
    and DEV_RATE_LIMIT_BYPASS_PHONES env vars."""
    phones: list[str] = []
    for env_name in ("REVIEWER_TEST_PHONE", "DEV_RATE_LIMIT_BYPASS_PHONES"):
        raw = os.getenv(env_name, "")
        for p in raw.split(","):
            p = p.strip()
            if p and p not in phones:
                phones.append(p)
    return phones


class TestSendPhoneResult(BaseModel):
    phone: str
    user_found: bool
    tokens_found: int
    sent: int
    failed: int


class TestSendResponseDTO(BaseModel):
    phones: list[TestSendPhoneResult]
    total_sent: int
    total_failed: int


class TestPhonesResponseDTO(BaseModel):
    phones: list[str]


@router.get(
    "/test-phones",
    response_model=TestPhonesResponseDTO,
    summary="Текущие тестовые номера (для отображения в админке)",
    description=(
        "Возвращает номера, реально настроенные на бэкенде через "
        "REVIEWER_TEST_PHONE + DEV_RATE_LIMIT_BYPASS_PHONES — те же, на "
        "которые уйдёт POST /send-test. Админка использует этот эндпоинт "
        "вместо хардкода, чтобы список в UI никогда не расходился с "
        "реальной конфигурацией (см. историю задачи 'Пуш')."
    ),
)
async def get_test_phones() -> TestPhonesResponseDTO:
    return TestPhonesResponseDTO(phones=_get_test_phones())


@router.post(
    "/send-test",
    response_model=TestSendResponseDTO,
    summary="Тестовая отправка на номера ревьюеров/девелоперов",
    description=(
        "Отправляет пуш только на устройства, привязанные к тестовым номерам "
        "(REVIEWER_TEST_PHONE + DEV_RATE_LIMIT_BYPASS_PHONES). "
        "Используйте перед broadcast-рассылкой чтобы проверить как выглядит уведомление."
    ),
    responses={**get_common_responses("create")},
)
async def send_test_push(
    request: SendNotificationRequestDTO,
    database: Database = Depends(get_database),
    firebase_client: FirebaseNotificationClient = Depends(get_firebase_client),
    idp: IdentityProviderClientKeycloak = Depends(get_identity_provider_client_keycloak),
):
    if not firebase_client.enabled:
        raise HTTPException(
            status_code=503,
            detail="Firebase notifications are disabled. Configure firebase__enabled and credentials.",
        )

    test_phones = _get_test_phones()
    if not test_phones:
        raise HTTPException(
            status_code=400,
            detail="No test phones configured. Set REVIEWER_TEST_PHONE or DEV_RATE_LIMIT_BYPASS_PHONES.",
        )

    phone_results: list[TestSendPhoneResult] = []
    all_tokens: list[str] = []
    phone_token_map: dict[str, list[str]] = {}

    session = database.session
    try:
        for phone in test_phones:
            try:
                user = idp.get(KeycloakUserQueryDTO(phone=phone))
                user_id: UUID = user.id
            except Exception:
                phone_results.append(TestSendPhoneResult(
                    phone=phone, user_found=False, tokens_found=0, sent=0, failed=0,
                ))
                continue

            tokens_rows = (
                session.query(DailyTestDeviceToken)
                .filter(DailyTestDeviceToken.student_guid == user_id)
                .all()
            )
            tokens = [row.token for row in tokens_rows if row.token]
            phone_token_map[phone] = tokens
            all_tokens.extend(tokens)
            phone_results.append(TestSendPhoneResult(
                phone=phone, user_found=True, tokens_found=len(tokens),
                sent=0, failed=0,
            ))
    finally:
        session.close()

    if not all_tokens:
        logger.warning("Test push: no FCM tokens found for phones %s", test_phones)
        return TestSendResponseDTO(phones=phone_results, total_sent=0, total_failed=0)

    send_result = firebase_client.broadcast(
        all_tokens,
        title=request.title,
        body=request.body,
        data={"type": "admin_test_push"},
    )
    logger.info(
        "Test push sent: phones=%s tokens=%d success=%d failure=%d",
        test_phones, len(all_tokens), send_result.success, send_result.failure,
    )

    # Distribute sent/failed counts back to per-phone results
    tokens_per_phone = {
        phone: len(toks) for phone, toks in phone_token_map.items()
    }
    total_tokens = len(all_tokens)
    for r in phone_results:
        if r.tokens_found == 0:
            continue
        share = r.tokens_found / total_tokens if total_tokens else 0
        r.sent = round(send_result.success * share)
        r.failed = r.tokens_found - r.sent

    return TestSendResponseDTO(
        phones=phone_results,
        total_sent=send_result.success,
        total_failed=send_result.failure,
    )


# ---------------------------------------------------------------------------
# Personal send: fire a push to a single user by their phone number.
# ---------------------------------------------------------------------------

class SendToPhoneRequestDTO(BaseModel):
    phone: str = Field(..., min_length=5, max_length=20)
    title: str = Field(..., min_length=1, max_length=100)
    body: str = Field(..., min_length=1, max_length=500)


class SendToPhoneResponseDTO(BaseModel):
    phone: str
    user_found: bool
    tokens_found: int
    sent: int
    failed: int


@router.post(
    "/send-to-phone",
    response_model=SendToPhoneResponseDTO,
    summary="Личная отправка пуша по номеру телефона",
    description="Отправляет push-уведомление конкретному пользователю по номеру телефона.",
    responses={**get_common_responses("create")},
)
async def send_push_to_phone(
    request: SendToPhoneRequestDTO,
    database: Database = Depends(get_database),
    firebase_client: FirebaseNotificationClient = Depends(get_firebase_client),
    idp: IdentityProviderClientKeycloak = Depends(get_identity_provider_client_keycloak),
):
    if not firebase_client.enabled:
        raise HTTPException(
            status_code=503,
            detail="Firebase notifications are disabled. Configure firebase__enabled and credentials.",
        )

    session = database.session
    try:
        try:
            user = idp.get(KeycloakUserQueryDTO(phone=request.phone))
            user_id: UUID = user.id
        except Exception:
            return SendToPhoneResponseDTO(
                phone=request.phone, user_found=False, tokens_found=0, sent=0, failed=0,
            )

        tokens_rows = (
            session.query(DailyTestDeviceToken)
            .filter(DailyTestDeviceToken.student_guid == user_id)
            .all()
        )
        tokens = [row.token for row in tokens_rows if row.token]
    finally:
        session.close()

    if not tokens:
        logger.warning("Personal push: no FCM tokens for phone %s (user %s)", request.phone, user_id)
        return SendToPhoneResponseDTO(
            phone=request.phone, user_found=True, tokens_found=0, sent=0, failed=0,
        )

    send_result = firebase_client.broadcast(
        tokens,
        title=request.title,
        body=request.body,
        data={"type": "admin_personal_push"},
    )
    logger.info(
        "Personal push sent: phone=%s user=%s tokens=%d success=%d failure=%d",
        request.phone, user_id, len(tokens), send_result.success, send_result.failure,
    )

    return SendToPhoneResponseDTO(
        phone=request.phone,
        user_found=True,
        tokens_found=len(tokens),
        sent=send_result.success,
        failed=send_result.failure,
    )
