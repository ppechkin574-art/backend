"""Admin CRUD for the daily streak reward tiers."""

from fastapi import APIRouter, Depends

from api.dependencies import allow_read_or_admin_write, get_streak_bonus_service
from streak_bonus.dtos import (
    StreakRewardTierCreateDTO,
    StreakRewardTierDTO,
    StreakRewardTierUpdateDTO,
)
from streak_bonus.service import StreakBonusService

router = APIRouter(
    prefix="/admin/streak-reward-tiers",
    tags=["admin"],
    dependencies=[Depends(allow_read_or_admin_write)],
)


@router.get("", response_model=list[StreakRewardTierDTO])
def list_tiers(
    service: StreakBonusService = Depends(get_streak_bonus_service),
):
    return [StreakRewardTierDTO.model_validate(t) for t in service.list_tiers()]


@router.post("", response_model=StreakRewardTierDTO, status_code=201)
def create_tier(
    body: StreakRewardTierCreateDTO,
    service: StreakBonusService = Depends(get_streak_bonus_service),
):
    tier = service.create_tier(body)
    service.repo.db.commit()
    return StreakRewardTierDTO.model_validate(tier)


@router.get("/{min_streak}", response_model=StreakRewardTierDTO)
def get_tier(
    min_streak: int,
    service: StreakBonusService = Depends(get_streak_bonus_service),
):
    return StreakRewardTierDTO.model_validate(service.get_tier(min_streak))


@router.patch("/{min_streak}", response_model=StreakRewardTierDTO)
def update_tier(
    min_streak: int,
    body: StreakRewardTierUpdateDTO,
    service: StreakBonusService = Depends(get_streak_bonus_service),
):
    tier = service.update_tier(min_streak, body)
    service.repo.db.commit()
    return StreakRewardTierDTO.model_validate(tier)


@router.delete("/{min_streak}", status_code=204)
def delete_tier(
    min_streak: int,
    service: StreakBonusService = Depends(get_streak_bonus_service),
):
    service.delete_tier(min_streak)
    service.repo.db.commit()
