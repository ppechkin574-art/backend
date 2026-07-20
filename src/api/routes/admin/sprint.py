"""Admin controls for the weekly sprint — the "Турнир → Спринт" page.

CRM #19. The threshold, prize and card copy themselves live on the shared
settings row and are edited through `PATCH /admin/leaderboard-points/settings`
(partial payload); everything sprint-specific is here:

- GET    /admin/sprint/participants                  — the allowlist
- POST   /admin/sprint/participants                  — let someone in
- DELETE /admin/sprint/participants/{id}             — remove them
- GET    /admin/sprint/current                       — week in progress
- GET    /admin/sprint/history                       — past weeks
- POST   /admin/sprint/weeks/{week_start}/resolve-tie — split a tied prize

Display names/avatars are resolved with the same `user_display` snapshot →
Keycloak fallback chain the public leaderboard uses, imported from the user
route rather than reimplemented, so the admin sees exactly the names players
see.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.dependencies import (
    allow_read_or_admin_write,
    get_cache_service,
    get_db_session,
    get_identity_provider_client_keycloak,
    get_sprint_service,
)
from auth.dtos.users import UserDTO
from clients.identity_provider.client import IdentityProviderClientKeycloak
from leaderboard_points.dtos import (
    SprintCurrentDTO,
    SprintHistoryEntryDTO,
    SprintParticipantCreateDTO,
    SprintParticipantDTO,
    SprintStandingDTO,
    SprintTieResolveResultDTO,
    SprintWinnerEntryDTO,
)
from leaderboard_points.sprint import InvalidPhoneNumber, SprintService
from quiz.repositories.user_display import UserDisplayRepository
from utils.cache import CacheService

router = APIRouter(
    prefix="/admin/sprint",
    tags=["admin"],
    dependencies=[Depends(allow_read_or_admin_write)],
)


def _names_for(
    user_ids: list[str],
    session: Session,
    idp: IdentityProviderClientKeycloak,
    cache: CacheService,
) -> dict[str, str]:
    """user_id → display name, via the public leaderboard's resolver.

    Imported lazily from the user route because that module owns the
    resolution chain (snapshot → Keycloak → PII-safe fallback) and importing
    it at module load would create a routes-import-routes cycle. Avatars are
    intentionally not resolved here — the admin tables show names only, and
    each avatar costs a presigned-URL round trip."""
    if not user_ids:
        return {}
    from api.routes.user.leaderboard import _commit_backfill, _resolve_display

    display_repo = UserDisplayRepository(session)
    snapshots = display_repo.bulk_get(user_ids)
    names: dict[str, str] = {}
    wrote_any = False
    for uid in user_ids:
        display, wrote = _resolve_display(uid, snapshots, idp, cache, display_repo)
        wrote_any = wrote_any or wrote
        names[uid] = display[0] if display is not None else "Пользователь"
    if wrote_any:
        _commit_backfill(session)
    return names


# ---------- participants ----------


@router.get("/participants", response_model=list[SprintParticipantDTO])
def list_participants(
    session: Session = Depends(get_db_session),
    idp: IdentityProviderClientKeycloak = Depends(get_identity_provider_client_keycloak),
    cache: CacheService = Depends(get_cache_service),
    service: SprintService = Depends(get_sprint_service),
):
    rows = service.list_participants()
    names = _names_for(
        [str(r.user_id) for r in rows if r.user_id is not None], session, idp, cache
    )
    return [
        SprintParticipantDTO(
            id=r.id,
            phone_number=r.phone_number,
            user_id=str(r.user_id) if r.user_id else None,
            user_display=names.get(str(r.user_id)) if r.user_id else None,
            added_by_display=r.added_by_display,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post(
    "/participants",
    response_model=SprintParticipantDTO,
    status_code=status.HTTP_201_CREATED,
)
def add_participant(
    body: SprintParticipantCreateDTO,
    user: UserDTO = Depends(allow_read_or_admin_write),
    service: SprintService = Depends(get_sprint_service),
):
    """Two entry paths, one endpoint: the admin either picks an existing
    account (`user_id` + its phone) or types a bare number for someone who
    paid but has not registered yet. Adding an existing number is idempotent
    — it returns the same row rather than erroring, because admins add people
    as payments arrive and a double submit must not fail."""
    actor_display = user.name or user.email or str(user.id)
    try:
        participant, _created = service.add_participant(
            body.phone_number, body.user_id, actor_display
        )
    except InvalidPhoneNumber as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Номер должен быть в формате +77001234567",
        ) from exc
    service.repo.db.commit()
    return SprintParticipantDTO(
        id=participant.id,
        phone_number=participant.phone_number,
        user_id=str(participant.user_id) if participant.user_id else None,
        user_display=None,
        added_by_display=participant.added_by_display,
        created_at=participant.created_at,
    )


@router.delete("/participants/{participant_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_participant(
    participant_id: int,
    service: SprintService = Depends(get_sprint_service),
):
    """Drops the person from future standings. Any week they already won
    stays in history — recorded winners are never revoked."""
    if not service.remove_participant(participant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    service.repo.db.commit()


# ---------- current week & history ----------


@router.get("/current", response_model=SprintCurrentDTO)
def current_week(
    session: Session = Depends(get_db_session),
    idp: IdentityProviderClientKeycloak = Depends(get_identity_provider_client_keycloak),
    cache: CacheService = Depends(get_cache_service),
    service: SprintService = Depends(get_sprint_service),
):
    data = service.current_week()
    ids = [str(u) for u, _, _ in data["standings"]]
    ids += [str(w.user_id) for w in data["winners"]]
    names = _names_for(list(dict.fromkeys(ids)), session, idp, cache)

    return SprintCurrentDTO(
        week_start_at=data["week_start_at"],
        week_end_at=data["week_end_at"],
        target_points=data["target_points"],
        prize_amount=data["prize_amount"],
        participant_count=data["participant_count"],
        winners=[
            SprintWinnerEntryDTO(
                user_id=str(w.user_id),
                name=names.get(str(w.user_id), "Пользователь"),
                points=w.points_at_win,
                resolution_type=w.resolution_type,
                prize_share=w.prize_share,
                won_at=w.won_at,
            )
            for w in data["winners"]
        ],
        standings=[
            SprintStandingDTO(
                user_id=str(uid),
                name=names.get(str(uid), "Пользователь"),
                points=points,
            )
            for uid, points, _ in data["standings"]
        ],
    )


@router.get("/history", response_model=list[SprintHistoryEntryDTO])
def history(
    limit: int = Query(100, ge=1, le=500),
    session: Session = Depends(get_db_session),
    idp: IdentityProviderClientKeycloak = Depends(get_identity_provider_client_keycloak),
    cache: CacheService = Depends(get_cache_service),
    service: SprintService = Depends(get_sprint_service),
):
    rows = service.history(limit=limit)
    names = _names_for(
        list(dict.fromkeys(str(r.user_id) for r in rows)), session, idp, cache
    )
    return [
        SprintHistoryEntryDTO(
            week_start_at=r.week_start_at,
            user_id=str(r.user_id),
            name=names.get(str(r.user_id), "Пользователь"),
            points=r.points_at_win,
            resolution_type=r.resolution_type,
            prize_share=r.prize_share,
            won_at=r.won_at,
        )
        for r in rows
    ]


# ---------- tie resolution ----------


@router.post(
    "/weeks/{week_start_at}/resolve-tie", response_model=SprintTieResolveResultDTO
)
def resolve_tie(
    week_start_at: datetime,
    user: UserDTO = Depends(allow_read_or_admin_write),
    service: SprintService = Depends(get_sprint_service),
):
    """Split the configured prize evenly between a week's tied winners.

    Deliberately a manual admin action rather than something the week-close
    job does by itself: an even split is a payout decision, and the operator
    should see who tied before committing to it. 404 when the week has no
    pending tie — either it was already resolved or it never tied."""
    actor_display = user.name or user.email or str(user.id)
    count, share = service.resolve_tie(week_start_at, actor_display)
    if count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="У этой недели нет неразрешённой ничьей",
        )
    service.repo.db.commit()
    return SprintTieResolveResultDTO(
        week_start_at=week_start_at, winners_count=count, prize_share=share
    )
