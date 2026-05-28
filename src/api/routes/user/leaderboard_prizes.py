"""User-facing read of leaderboard prizes.

GET /user/leaderboard-prizes — list active prizes ordered by rank.
Drives the «gift bubble» modal on the iOS leaderboard screen.
"""

from fastapi import APIRouter, Depends

from api.dependencies import get_leaderboard_prize_service, get_user
from leaderboard_prizes.dtos import LeaderboardPrizeDTO
from leaderboard_prizes.service import LeaderboardPrizeService

router = APIRouter(
    prefix="/user/leaderboard-prizes",
    tags=["User - Leaderboard"],
    dependencies=[Depends(get_user)],
)


@router.get("", response_model=list[LeaderboardPrizeDTO])
def list_active_prizes(
    service: LeaderboardPrizeService = Depends(get_leaderboard_prize_service),
):
    """Активные призы для топа лидерборда. Отсортировано по rank."""
    return [
        LeaderboardPrizeDTO.model_validate(p)
        for p in service.list_active_prizes()
    ]
