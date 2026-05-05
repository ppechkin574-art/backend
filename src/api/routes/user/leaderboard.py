from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from api.dependencies import get_db_session, get_identity_provider_client_keycloak
from quiz.repositories.user_points import UserPointsRepository
from clients.identity_provider.client import IdentityProviderClientKeycloak

router = APIRouter(prefix="/leaderboard", tags=["Leaderboard"])


class LeaderboardEntry(BaseModel):
    rank: int
    user_id: str
    name: str
    avatar: str | None
    total_points: int


@router.get("", response_model=list[LeaderboardEntry])
async def get_leaderboard(
    limit: int = Query(100, ge=1, le=500),
    session: Session = Depends(get_db_session),
    idp: IdentityProviderClientKeycloak = Depends(
        get_identity_provider_client_keycloak
    ),
):
    points_repo = UserPointsRepository(session)
    top = points_repo.get_all_ranked(limit)

    if not top:
        return []

    user_ids = [str(user_id) for user_id, _ in top]
    users_map = {}
    for uid in user_ids:
        try:
            kc_user = idp.get_user(
                uid
            )  # должен быть реализован метод get_user в клиенте
            if kc_user:
                name = (
                    kc_user.attributes.name[0]
                    if kc_user.attributes and kc_user.attributes.name
                    else ""
                )
                avatar = (
                    kc_user.attributes.avatar[0]
                    if kc_user.attributes and kc_user.attributes.avatar
                    else None
                )
                users_map[uid] = (name, avatar)
        except Exception:
            continue

    result = []
    for idx, (user_id, points) in enumerate(top, start=1):
        name, avatar = users_map.get(str(user_id), ("Unknown", None))
        result.append(
            LeaderboardEntry(
                rank=idx,
                user_id=str(user_id),
                name=name or "Пользователь",
                avatar=avatar,
                total_points=points,
            )
        )
    return result
