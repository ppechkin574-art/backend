import logging
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.containers import Container
from api.dependencies import allow_read_or_admin_write, get_database, get_settings
from api.exceptions.documentation import get_common_responses
from clients.firebase import FirebaseNotificationClient
from clients.firebase.settings import FirebaseSettings
from database import Database
from quiz.services.daily_test_notifications import DailyTestNotificationService
from settings import Settings

router = APIRouter(
    prefix="/admin/notifications",
    tags=["Admin - Notifications (Test)"],
    dependencies=[Depends(allow_read_or_admin_write)],
)

logger = logging.getLogger(__name__)


class TestNotificationRequestDTO(BaseModel):
    """DTO for test notification request"""

    title: str = Field(..., description="Notification title")
    body: str = Field(..., description="Notification body")
    target_user_id: UUID | None = Field(
        default=None,
        description="Send only to this user (UUID). Omit to send to ALL devices.",
    )


class TestNotificationResponseDTO(BaseModel):
    """DTO for test notification response"""

    requested: int = Field(..., description="Number of devices requested")
    delivered: int = Field(..., description="Number of notifications delivered")
    failed: int = Field(..., description="Number of notifications failed")
    removed_tokens: int = Field(..., description="Number of invalid tokens removed")


@inject
def get_firebase_client(
    firebase_client: FirebaseNotificationClient = Depends(Provide[Container.firebase_client]),
) -> FirebaseNotificationClient:
    """Get Firebase notification client"""
    return firebase_client


def get_firebase_settings(
    settings: Settings = Depends(get_settings),
) -> FirebaseSettings:
    """Get Firebase settings"""
    return settings.firebase


def get_notification_service(
    database: Database = Depends(get_database),
    firebase_client: FirebaseNotificationClient = Depends(get_firebase_client),
    firebase_settings: FirebaseSettings = Depends(get_firebase_settings),
) -> DailyTestNotificationService:
    """Get daily test notification service"""
    return DailyTestNotificationService(
        database=database,
        firebase_client=firebase_client,
        firebase_settings=firebase_settings,
    )


@router.post(
    "/test/send",
    response_model=TestNotificationResponseDTO,
    summary="Отправить тестовое уведомление",
    description="Отправляет тестовое уведомление всем устройствам в базе данных (только для тестирования)",
    responses={
        **get_common_responses("create"),
    },
)
async def send_test_notification(
    request: TestNotificationRequestDTO,
    notification_service: DailyTestNotificationService = Depends(get_notification_service),
):
    """
    Send test notification to all devices in the database.
    This is a test endpoint and should be removed in production.
    """
    logger.info(
        "Test notification request received",
        extra={
            "title": request.title,
            "body": request.body,
        },
    )

    if not notification_service.enabled:
        raise HTTPException(
            status_code=400,
            detail="Firebase notifications are disabled. Please enable them in settings and configure credentials_path.",
        )

    try:
        if request.target_user_id is not None:
            result = notification_service.send_test_to_user(
                request.target_user_id,
                title=request.title,
                body=request.body,
            )
        else:
            result = notification_service.send_daily_notifications(
                title=request.title,
                body=request.body,
                data={"type": "test"},
            )

        logger.info(
            "Test notification sent",
            extra={
                "requested": result.requested,
                "delivered": result.delivered,
                "failed": result.failed,
                "removed_tokens": result.removed_tokens,
                "target_user_id": str(request.target_user_id) if request.target_user_id else "all",
            },
        )

        return TestNotificationResponseDTO(
            requested=result.requested,
            delivered=result.delivered,
            failed=result.failed,
            removed_tokens=result.removed_tokens,
        )
    except Exception as e:
        logger.exception("Failed to send test notification")
        raise HTTPException(status_code=500, detail=f"Failed to send notification: {str(e)}")
