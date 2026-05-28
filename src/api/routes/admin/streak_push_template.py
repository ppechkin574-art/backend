"""Admin GET/PUT for the streak-reminder push template (singleton).

The streak-reminder cron re-reads this row on every tick, so changes
made through the admin panel propagate on the next firing without a
redeploy. There is no POST/DELETE — the row is seeded by the migration
and is always exactly one row (CHECK id=1 enforced at the DB level).
"""

from fastapi import APIRouter, Depends

from api.dependencies import allow_only_admins, get_streak_bonus_service
from streak_bonus.dtos import StreakPushTemplateDTO, StreakPushTemplateUpdateDTO
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
