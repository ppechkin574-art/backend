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


def _user_display_pair(
    idp: IdentityProviderClientKeycloak, user_id: str
) -> tuple[str, str | None] | None:
    """Returns (name, raw_avatar_filename) for a Keycloak user id, or
    `None` when the user has been removed from Keycloak entirely
    (orphan in `user_points` table) so the caller can filter them
    out of the leaderboard response instead of rendering ghost rows
    labelled "Пользователь".

    Why `None` instead of a fallback tuple as before: after deleting
    the 5 seed leaderboard mocks on 18.05.2026, their `user_points`
    rows were NOT cleaned up (cascade-on-delete isn't configured
    between Keycloak and our Postgres). The home screen then showed
    three generic "Пользователь" rows with the seed point totals
    (4500/5000/4000), defeating the purpose of the delete.

    Soft errors (Keycloak unreachable, transient 5xx) still fall
    back to ("Пользователь", None) — we only treat "user explicitly
    not found" as an orphan to keep the leaderboard alive during
    Keycloak outages.
    """
    try:
        kc_user = idp.get_user(user_id)
    except Exception:
        # Transient lookup failure (network, Keycloak 5xx) — keep
        # the user in the leaderboard with a placeholder rather
        # than hiding them. Real outage shouldn't blank the screen.
        return ("Пользователь", None)
    if not kc_user:
        # Keycloak responded "no such user" — this is an orphan,
        # signal the caller to skip.
        return None
    name = ""
    if kc_user.attributes and kc_user.attributes.name:
        name = kc_user.attributes.name[0] or ""
    avatar = None
    if kc_user.attributes and kc_user.attributes.avatar:
        avatar = kc_user.attributes.avatar[0] or None
    return (name or "Пользователь", avatar)


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
    rank_counter = 0
    for user_id, points in top:
        display = _user_display_pair(idp, str(user_id))
        if display is None:
            # Orphan — user was deleted from Keycloak but their
            # points rows remain in Postgres. Skip the row entirely
            # so it doesn't render as a ghost "Пользователь".
            # Rank numbering is computed AFTER filtering so the
            # visible top-N is gap-free.
            continue
        rank_counter += 1
        name, raw_avatar = display
        result.append(
            LeaderboardEntry(
                rank=rank_counter,
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
