from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.dependencies import (
    get_db_session,
    get_file_service,
    get_identity_provider_client_keycloak,
    get_user,
)
from auth.dtos.users import UserDTO
from clients.identity_provider.client import IdentityProviderClientKeycloak
from quiz.repositories.user_points import UserPointsRepository
from utils.file_service import FileService

router = APIRouter(prefix="/leaderboard", tags=["Leaderboard"])


class LeaderboardEntry(BaseModel):
    rank: int
    user_id: str
    name: str
    avatar_url: str | None
    total_points: int


class MyRankEntry(BaseModel):
    rank: int
    user_id: str
    name: str
    avatar_url: str | None
    total_points: int


def _resolve_avatar(raw_avatar: str | None, file_service: FileService) -> str | None:
    """Convert the avatar attribute stored in Keycloak (a filename like
    `<user_id>_<hash>.jpg`) into a presigned URL the mobile app can
    render.  Returns None when the user hasn't uploaded an avatar so
    the client falls back to the initials placeholder."""
    if not raw_avatar:
        return None
    try:
        url = file_service.get_avatar_url(raw_avatar)
        return url or None
    except Exception:
        return None


def _user_display_pair(idp: IdentityProviderClientKeycloak, user_id: str) -> tuple[str, str | None]:
    """Returns (name, raw_avatar_filename) for a Keycloak user id, with
    safe fallbacks when the directory call fails or attributes are
    missing."""
    try:
        kc_user = idp.get_user(user_id)
        if not kc_user:
            return ("Пользователь", None)
        name = ""
        if kc_user.attributes and kc_user.attributes.name:
            name = kc_user.attributes.name[0] or ""
        avatar = None
        if kc_user.attributes and kc_user.attributes.avatar:
            avatar = kc_user.attributes.avatar[0] or None
        return (name or "Пользователь", avatar)
    except Exception:
        return ("Пользователь", None)


@router.get(
    "",
    response_model=list[LeaderboardEntry],
    summary="Топ пользователей по очкам",
)
async def get_leaderboard(
    limit: int = Query(100, ge=1, le=500),
    session: Session = Depends(get_db_session),
    idp: IdentityProviderClientKeycloak = Depends(get_identity_provider_client_keycloak),
    file_service: FileService = Depends(get_file_service),
):
    points_repo = UserPointsRepository(session)
    top = points_repo.get_all_ranked(limit)
    if not top:
        return []

    result: list[LeaderboardEntry] = []
    for idx, (user_id, points) in enumerate(top, start=1):
        name, raw_avatar = _user_display_pair(idp, str(user_id))
        result.append(
            LeaderboardEntry(
                rank=idx,
                user_id=str(user_id),
                name=name,
                avatar_url=_resolve_avatar(raw_avatar, file_service),
                total_points=points,
            )
        )
    return result


@router.get(
    "/me",
    response_model=MyRankEntry,
    summary="Место и очки текущего пользователя",
)
async def get_my_rank(
    user: UserDTO = Depends(get_user),
    session: Session = Depends(get_db_session),
    idp: IdentityProviderClientKeycloak = Depends(get_identity_provider_client_keycloak),
    file_service: FileService = Depends(get_file_service),
):
    points_repo = UserPointsRepository(session)
    total = points_repo.get_total_points(user.id)
    rank = points_repo.get_user_rank(user.id) if total > 0 else 0

    name, raw_avatar = _user_display_pair(idp, str(user.id))
    return MyRankEntry(
        rank=rank,
        user_id=str(user.id),
        name=name,
        avatar_url=_resolve_avatar(raw_avatar, file_service),
        total_points=total,
    )
