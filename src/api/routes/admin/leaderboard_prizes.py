"""Admin CRUD for leaderboard prizes.

Endpoints (all gated by `allow_only_admins`):
- GET    /admin/leaderboard-prizes              — list all (active + inactive)
- POST   /admin/leaderboard-prizes              — create
- GET    /admin/leaderboard-prizes/icon-keys    — allowed icon_key values
- GET    /admin/leaderboard-prizes/{id}         — get one
- PATCH  /admin/leaderboard-prizes/{id}         — partial update
- DELETE /admin/leaderboard-prizes/{id}         — hard delete

`icon-keys` endpoint lets the admin web populate the icon-picker
dropdown without keeping a hardcoded copy in the frontend.
"""

from fastapi import APIRouter, Depends

from api.dependencies import allow_only_admins, get_leaderboard_prize_service
from leaderboard_prizes.dtos import (
    IconKeyListDTO,
    LeaderboardPrizeCreateDTO,
    LeaderboardPrizeDTO,
    LeaderboardPrizeUpdateDTO,
    PRIZE_ICON_KEYS,
)
from leaderboard_prizes.service import LeaderboardPrizeService

router = APIRouter(
    prefix="/admin/leaderboard-prizes",
    tags=["admin"],
    dependencies=[Depends(allow_only_admins)],
)


@router.get("", response_model=list[LeaderboardPrizeDTO])
def list_prizes(
    service: LeaderboardPrizeService = Depends(get_leaderboard_prize_service),
):
    return [LeaderboardPrizeDTO.model_validate(p) for p in service.list_all_prizes()]


@router.get("/icon-keys", response_model=IconKeyListDTO)
def list_icon_keys():
    """Список значений, валидных для поля `icon_key`. Используется
    admin-web для dropdown иконки в форме."""
    return IconKeyListDTO(icon_keys=list(PRIZE_ICON_KEYS))


@router.post("", response_model=LeaderboardPrizeDTO, status_code=201)
def create_prize(
    body: LeaderboardPrizeCreateDTO,
    service: LeaderboardPrizeService = Depends(get_leaderboard_prize_service),
):
    prize = service.create(body)
    service.repo.db.commit()
    return LeaderboardPrizeDTO.model_validate(prize)


@router.get("/{prize_id}", response_model=LeaderboardPrizeDTO)
def get_prize(
    prize_id: int,
    service: LeaderboardPrizeService = Depends(get_leaderboard_prize_service),
):
    return LeaderboardPrizeDTO.model_validate(service.get_one(prize_id))


@router.patch("/{prize_id}", response_model=LeaderboardPrizeDTO)
def update_prize(
    prize_id: int,
    body: LeaderboardPrizeUpdateDTO,
    service: LeaderboardPrizeService = Depends(get_leaderboard_prize_service),
):
    prize = service.update(prize_id, body)
    service.repo.db.commit()
    return LeaderboardPrizeDTO.model_validate(prize)


@router.delete("/{prize_id}", status_code=204)
def delete_prize(
    prize_id: int,
    service: LeaderboardPrizeService = Depends(get_leaderboard_prize_service),
):
    service.delete(prize_id)
    service.repo.db.commit()
