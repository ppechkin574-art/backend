"""Admin endpoints for the leaderboard hide-list.

Lets the operator hide selected users from the in-app leaderboard. A
hidden user is excluded from the ranking entirely (filtered in
`UserPointsRepository`), so everyone below shifts up — gap-free
positions 1, 2, 3… Top-3 podium prizes are display-by-rank only, so
hiding a user also removes them from prizes. The mobile app needs NO
change — the backend filters the ranking.

Endpoints (gated by `allow_read_or_admin_write`):
- GET  /admin/leaderboard/hidden — current hidden set { "user_ids": [...] }
- POST /admin/leaderboard/hidden — bulk hide/show, returns the updated set

The route owns the commit (mirrors leaderboard-prizes / app_update_config):
the service flushes, the route commits after a successful save.
"""

from fastapi import APIRouter, Depends

from api.dependencies import allow_read_or_admin_write, get_leaderboard_hidden_service
from quiz.dtos.leaderboard_hidden import (
    LeaderboardHiddenListDTO,
    LeaderboardHiddenUpdateDTO,
)
from quiz.services.leaderboard_hidden import LeaderboardHiddenService

router = APIRouter(
    prefix="/admin/leaderboard/hidden",
    tags=["admin"],
    dependencies=[Depends(allow_read_or_admin_write)],
)


@router.get(
    "",
    response_model=LeaderboardHiddenListDTO,
    summary="Текущий набор скрытых из лидерборда пользователей",
)
def get_hidden(
    service: LeaderboardHiddenService = Depends(get_leaderboard_hidden_service),
):
    return LeaderboardHiddenListDTO(user_ids=service.get_hidden())


@router.post(
    "",
    response_model=LeaderboardHiddenListDTO,
    summary="Скрыть/показать пользователей в лидерборде (bulk, идемпотентно)",
)
def set_hidden(
    body: LeaderboardHiddenUpdateDTO,
    service: LeaderboardHiddenService = Depends(get_leaderboard_hidden_service),
):
    updated = service.set_hidden(body.user_ids, body.hidden)
    service.repo.db.commit()
    return LeaderboardHiddenListDTO(user_ids=updated)
