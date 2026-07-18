"""Admin controls for leaderboard points — auto-reset schedule + selective
per-user adjustment. Surfaced in the admin panel's "Пользователи" section.

Endpoints (all protected by allow_read_or_admin_write):
- GET   /admin/leaderboard-points/settings        — current auto-reset config
- PATCH /admin/leaderboard-points/settings        — update it (restarts the countdown)
- POST  /admin/leaderboard-points/users/{id}/adjust — add/remove points for one user

Point history for a user is already served by
GET /admin/security/users/{user_id}/points-history (shared audit log,
`PointsAuditLog`) — not duplicated here.
"""

from uuid import UUID

from fastapi import APIRouter, Depends

from api.dependencies import allow_read_or_admin_write, get_leaderboard_points_service
from auth.dtos.users import UserDTO
from leaderboard_points.dtos import (
    LeaderboardPointsSettingsDTO,
    LeaderboardPointsSettingsUpdateDTO,
    PointsAdjustDTO,
    PointsAdjustResultDTO,
)
from leaderboard_points.service import LeaderboardPointsService

router = APIRouter(
    prefix="/admin/leaderboard-points",
    tags=["admin"],
    dependencies=[Depends(allow_read_or_admin_write)],
)


@router.get("/settings", response_model=LeaderboardPointsSettingsDTO)
def get_settings(
    service: LeaderboardPointsService = Depends(get_leaderboard_points_service),
):
    return service.get_settings()


@router.patch("/settings", response_model=LeaderboardPointsSettingsDTO)
def update_settings(
    body: LeaderboardPointsSettingsUpdateDTO,
    user: UserDTO = Depends(allow_read_or_admin_write),
    service: LeaderboardPointsService = Depends(get_leaderboard_points_service),
):
    actor_display = user.name or user.email or str(user.id)
    result = service.update_settings(body.auto_reset_enabled, body.interval_days, actor_display)
    service.repo.db.commit()
    return result


@router.post("/users/{user_id}/adjust", response_model=PointsAdjustResultDTO)
def adjust_points(
    user_id: UUID,
    body: PointsAdjustDTO,
    user: UserDTO = Depends(allow_read_or_admin_write),
    service: LeaderboardPointsService = Depends(get_leaderboard_points_service),
):
    actor_display = user.name or user.email or str(user.id)
    result = service.adjust_points(user_id, body.delta, body.reason, user.id, actor_display)
    service.repo.db.commit()
    return result
