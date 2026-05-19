import re

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
from clients.identity_provider import IdentityNotFound
from clients.identity_provider.client import IdentityProviderClientKeycloak
from quiz.repositories.user_points import UserPointsRepository
from utils.file_service import FileService

# Heuristics for spotting the Keycloak fallback (raw username / phone / email)
# that leaks into the leaderboard for legacy users registered before
# the DisplayName validator existed. See validators.validate_display_name.
_PHONE_OR_EMAIL_REGEX = re.compile(r"^[+\d][\d\s\-+()]*$|@")
# Keycloak auto-generates usernames like "user3" / "user-42" when a user
# is created without an explicit username (admin-panel flow, scripts).
# These are not PII but still look like placeholders and pollute the
# leaderboard, so we treat them the same as phone/email leaks.
_AUTO_USERNAME_REGEX = re.compile(r"^user[-_]?\d+$", re.IGNORECASE)


def _is_pii_leak(name: str) -> bool:
    """True when `name` looks like the Keycloak fallback rather than a
    real display name. Catches three legacy patterns:

      - Phone numbers (`+77001234567`, `7 700 123 4567`) — leaked when
        Keycloak uses phone as the username and the user's `name`
        attribute is empty.
      - Emails (anything with `@`).
      - Auto-generated usernames (`user3`, `user_42`) — admin-panel
        and seed-script artefacts.

    Empty string is also considered a leak (defensive — `name`
    should never be empty after the DisplayName validator, but the
    leaderboard route is the last line before public display).

    New registrations go through validate_display_name and can't
    produce any of these; this only protects the legacy accounts.
    """
    if not name:
        return True
    if _PHONE_OR_EMAIL_REGEX.search(name):
        return True
    if _AUTO_USERNAME_REGEX.match(name):
        return True
    return False


def _safe_display_name(name: str, user_id: str) -> str:
    """Render a privacy-safe display name for the leaderboard. If
    `name` looks like PII or is empty, fall back to
    "Пользователь #ABCD" using the last four hex characters of the
    user's UUID — stable across requests, anonymous, and visually
    distinct between users so the podium doesn't show three identical
    "Пользователь" rows."""
    if not _is_pii_leak(name):
        return name
    suffix = user_id.replace("-", "")[-4:].upper() if user_id else "????"
    return f"Пользователь #{suffix}"

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
    except IdentityNotFound:
        # Keycloak answered 404 — user is gone. This is the orphan
        # path. The Keycloak client wraps a 404 by RAISING
        # IdentityNotFound rather than returning None, so catching
        # generic Exception (the previous behaviour) collapsed this
        # case into the outage placeholder and the ghosts kept
        # rendering. Returning None signals the route to skip.
        return None
    except Exception:
        # Transient lookup failure (network, Keycloak 5xx) — keep
        # the user in the leaderboard with a placeholder rather
        # than hiding them. Real outage shouldn't blank the screen.
        return ("Пользователь", None)
    if not kc_user:
        # Defensive: future client refactor could switch from
        # raising to returning None — keep the orphan path here too.
        return None
    name = ""
    if kc_user.attributes and kc_user.attributes.name:
        name = kc_user.attributes.name[0] or ""
    avatar = None
    if kc_user.attributes and kc_user.attributes.avatar:
        avatar = kc_user.attributes.avatar[0] or None
    return (_safe_display_name(name, user_id), avatar)


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
    # Oversample at the SQL layer so orphan rows don't starve the
    # response for small `limit` values. Operator's 19.05.2026
    # screenshot: /leaderboard?limit=5 returned [] while
    # /leaderboard?limit=20 returned three valid users from the SAME
    # database. Reason — the five seed mocks deleted on 18.05.2026
    # still have user_points rows with 4000-5000 points (cascade-on-
    # delete is a TECH_DEBT item) and dominate the top of the
    # `ORDER BY total_points DESC` ranking. With LIMIT 5 the SQL
    # result was entirely those orphan rows, the post-fetch filter
    # dropped them all, and the API returned []. With LIMIT 20 the
    # SQL result reached past the orphans into the real users.
    # Tripling the fetch (capped at 200 to keep the Keycloak
    # round-trip count bounded) gives the filter enough headroom
    # to find `limit` valid users even when most of the top is
    # orphan rows. 200 is the same magnitude as the route's own
    # `le=500` query-param cap.
    oversample = min(limit * 3, 200)
    top = points_repo.get_all_ranked(oversample)
    if not top:
        return []

    result: list[LeaderboardEntry] = []
    rank_counter = 0
    for user_id, points in top:
        if rank_counter >= limit:
            # We've collected enough valid entries — stop iterating
            # so we don't waste Keycloak round-trips on the tail of
            # the oversampled fetch.
            break
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
