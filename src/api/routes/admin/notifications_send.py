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
from typing import Literal

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.containers import Container
from api.dependencies import (
    allow_only_admins,
    get_database,
    get_identity_provider_client_keycloak,
    get_settings,
)
from api.exceptions.documentation import get_common_responses
from clients.firebase import FirebaseNotificationClient
from clients.firebase.settings import FirebaseSettings
from clients.identity_provider.client import IdentityProviderClientKeycloak
from database import Database
from quiz.services.admin_broadcast_notifications import (
    AdminBroadcastNotificationService,
    BroadcastTarget,
)
from settings import Settings

router = APIRouter(
    prefix="/admin/notifications",
    tags=["Admin - Notifications"],
    dependencies=[Depends(allow_only_admins)],
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
