"""Admin GET/PUT for the streak-reminder push template (singleton).

The streak-reminder cron re-reads this row on every tick, so changes
made through the admin panel propagate on the next firing without a
redeploy. There is no POST/DELETE — the row is seeded by the migration
and is always exactly one row (CHECK id=1 enforced at the DB level).
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.dependencies import (
    allow_only_admins,
    get_streak_bonus_service,
    get_streak_reminder_service,
)
from streak_bonus.dtos import StreakPushTemplateDTO, StreakPushTemplateUpdateDTO
from streak_bonus.reminder_service import StreakReminderService
from streak_bonus.service import StreakBonusService

router = APIRouter(
    prefix="/admin/streak-push-template",
    tags=["admin"],
    dependencies=[Depends(allow_only_admins)],
)


@router.get("", response_model=StreakPushTemplateDTO)
def get_template(
    service: StreakBonusService = Depends(get_streak_bonus_service),
):
    return StreakPushTemplateDTO.model_validate(service.get_push_template())


@router.put("", response_model=StreakPushTemplateDTO)
def update_template(
    body: StreakPushTemplateUpdateDTO,
    service: StreakBonusService = Depends(get_streak_bonus_service),
):
    template = service.update_push_template(body)
    service.repo.db.commit()
    return StreakPushTemplateDTO.model_validate(template)


class TriggerDTO(BaseModel):
    """Manual cron trigger payload.

    - `target_user_id` set → test-send to just that user's FCM tokens
      with `fake_streak` substituted into the template. Bypasses the
      attendance_streaks audience query, so it works for QA accounts
      whose streak column wasn't populated by seed-streak.
    - `target_user_id` omitted → real broadcast (same path as the
      scheduled cron).
    """

    target_user_id: UUID | None = None
    fake_streak: int = Field(default=5, ge=1, le=365)


class TriggerResultDTO(BaseModel):
    requested: int
    delivered: int
    failed: int
    skipped_disabled: bool


@router.post("/trigger", response_model=TriggerResultDTO)
def trigger_now(
    body: TriggerDTO,
    reminder: StreakReminderService = Depends(get_streak_reminder_service),
):
    if body.target_user_id is not None:
        result = reminder.send_test_to_user(
            body.target_user_id, fake_streak=body.fake_streak
        )
    else:
        result = reminder.send_streak_reminders()
    return TriggerResultDTO(
        requested=result.requested,
        delivered=result.delivered,
        failed=result.failed,
        skipped_disabled=result.skipped_disabled,
    )
