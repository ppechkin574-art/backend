"""Admin GET/PUT/trigger for the daily notification push template (singleton).

The daily notification scheduler re-reads this row on every tick, so changes
propagate on the next firing without a redeploy. No POST/DELETE — the row
is seeded by the migration and is always exactly one row (CHECK id=1).
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.dependencies import (
    allow_only_admins,
    get_daily_notification_template_service,
    get_daily_test_notification_service,
)
from quiz.daily_notification_dtos import (
    DailyNotificationTemplateDTO,
    DailyNotificationTemplateUpdateDTO,
    DailyNotificationTriggerResultDTO,
)
from quiz.services.daily_notification_template import DailyNotificationTemplateService
from quiz.services.daily_test_notifications import DailyTestNotificationService

router = APIRouter(
    prefix="/admin/daily-notification-template",
    tags=["admin"],
    dependencies=[Depends(allow_only_admins)],
)


class TriggerDTO(BaseModel):
    """Manual cron trigger payload.

    - `target_user_id` set → test-send only to that user's FCM tokens.
      Safe for QA without disturbing other users.
    - `target_user_id` omitted → real broadcast to all registered devices.
    """

    target_user_id: UUID | None = Field(
        default=None,
        description="Send only to this user (UUID). Omit for full broadcast.",
    )


@router.get("/firebase-status")
def get_firebase_status(
    notification_service: DailyTestNotificationService = Depends(get_daily_test_notification_service),
):
    """Returns whether Firebase Cloud Messaging is enabled on this instance."""
    return {"enabled": notification_service.enabled}


@router.get("", response_model=DailyNotificationTemplateDTO)
def get_template(
    service: DailyNotificationTemplateService = Depends(get_daily_notification_template_service),
):
    return DailyNotificationTemplateDTO.model_validate(service.get())


@router.put("", response_model=DailyNotificationTemplateDTO)
def update_template(
    body: DailyNotificationTemplateUpdateDTO,
    service: DailyNotificationTemplateService = Depends(get_daily_notification_template_service),
):
    template = service.update(body)
    service._session.commit()
    return DailyNotificationTemplateDTO.model_validate(template)


@router.post("/trigger", response_model=DailyNotificationTriggerResultDTO)
def trigger_now(
    body: TriggerDTO = TriggerDTO(),
    template_service: DailyNotificationTemplateService = Depends(get_daily_notification_template_service),
    notification_service: DailyTestNotificationService = Depends(get_daily_test_notification_service),
):
    template = template_service.get()
    if not notification_service.enabled:
        return DailyNotificationTriggerResultDTO(
            requested=0, delivered=0, failed=0, skipped_disabled=True
        )

    if body.target_user_id is not None:
        result = notification_service.send_test_to_user(
            body.target_user_id,
            title=template.title,
            body=template.body,
        )
        return DailyNotificationTriggerResultDTO(
            requested=result.requested,
            delivered=result.delivered,
            failed=result.failed,
            skipped_disabled=False,
        )

    if not template.enabled:
        return DailyNotificationTriggerResultDTO(
            requested=0, delivered=0, failed=0, skipped_disabled=True
        )

    result = notification_service.send_daily_notifications(
        title=template.title,
        body=template.body,
    )
    return DailyNotificationTriggerResultDTO(
        requested=result.requested,
        delivered=result.delivered,
        failed=result.failed,
        skipped_disabled=False,
    )
