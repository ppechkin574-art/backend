import re
from datetime import datetime, timedelta, timezone, UTC

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.dependencies import (
    get_cache_service,
    get_db_session,
    get_file_service,
    get_identity_provider_client_keycloak,
    get_leaderboard_points_service,
    get_user,
)
from auth.dtos.users import UserDTO
from clients.identity_provider import IdentityNotFound
from clients.identity_provider.client import IdentityProviderClientKeycloak
from leaderboard_points.dtos import SprintWinnerDTO
from leaderboard_points.service import LeaderboardPointsService
from quiz.repositories.user_display import UserDisplayRepository
from quiz.repositories.user_points import UserPointsRepository
from utils.cache import CacheService, CacheStrategy
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
    return bool(_AUTO_USERNAME_REGEX.match(name))


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

def _milestone_rank(rank: int) -> int | None:
    """Nearest milestone tier above the user's rank (100 → 50 → 10 → 3)."""
    if rank > 100:
        return 100
    if rank > 50:
        return 50
    if rank > 10:
        return 10
    if rank > 3:
        return 3
    return None


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
    milestone_rank: int | None = None
    gap_to_milestone_pts: int | None = None


class SprintStatusEntry(BaseModel):
    """Response shape for GET /leaderboard/sprint (CRM task #7,
    "Еженедельный спринт"). Always a 200 with this shape — never a 404
    — so the mobile client doesn't need a special "not configured"
    error path: `target_points`/`week_start_at`/`winner` are simply
    null when the admin hasn't configured a sprint threshold yet."""

    target_points: int | None
    week_start_at: datetime | None
    winner: SprintWinnerDTO | None


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


_LB_DISPLAY_TTL = 900  # 15 min — name/avatar freshness vs Keycloak round-trips


def _cached_display_pair(
    idp: IdentityProviderClientKeycloak,
    cache: CacheService,
    user_id: str,
) -> tuple[str, str | None] | None:
    """Redis-cached wrapper over `_user_display_pair`.

    Leaderboard renders enrich every row from Keycloak (one Admin-API call per
    user — /me did up to 200 serial calls). Caching (name, avatar) per user makes
    repeat renders skip Keycloak entirely. The orphan (deleted-user) result is
    negative-cached too. The transient Keycloak-outage placeholder ("Пользователь"
    without "#XXXX") is NOT cached, so it refreshes to the real name on recovery.
    """
    key = cache.make_key(CacheStrategy.GLOBAL, resource="lb_display", params=user_id)
    hit = cache.get(key)
    if hit is not None:
        if hit.get("orphan"):
            return None
        return (hit["name"], hit.get("avatar"))

    pair = _user_display_pair(idp, user_id)
    if pair is None:
        cache.set(key, {"orphan": True}, ttl=_LB_DISPLAY_TTL)
        return None
    if pair == ("Пользователь", None):
        return pair  # transient outage — don't cache the placeholder
    cache.set(key, {"name": pair[0], "avatar": pair[1]}, ttl=_LB_DISPLAY_TTL)
    return pair


# Denormalized snapshot (Postgres `user_display`): the leaderboard reads
# names/avatars from one bulk SQL query instead of N Keycloak calls. A snapshot
# older than this is re-validated against Keycloak so name/avatar changes
# propagate without a per-profile-update hook.
_DISPLAY_FRESH = timedelta(hours=6)


def _is_fresh(updated_at) -> bool:
    if updated_at is None:
        return False
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - updated_at < _DISPLAY_FRESH


def _resolve_display(
    user_id: str,
    snapshots: dict,
    idp: IdentityProviderClientKeycloak,
    cache: CacheService,
    display_repo: UserDisplayRepository,
) -> tuple[tuple[str, str | None] | None, bool]:
    """Resolve a user's (name, avatar) for the leaderboard.

    Reads the bulk-fetched Postgres snapshot first — a FRESH hit means zero
    Keycloak calls. On a miss or a stale row, falls back to the Redis-cached
    Keycloak lookup and persists the result so the next render is pure SQL.
    Returns ``(pair_or_None, did_write)``. Orphans (deleted users) and the
    transient-outage placeholder are never persisted.
    """
    snap = snapshots.get(user_id)
    if snap is not None and _is_fresh(snap[2]):
        return (snap[0], snap[1]), False

    pair = _cached_display_pair(idp, cache, user_id)
    if pair is None:
        return None, False
    if pair == ("Пользователь", None):
        return pair, False
    display_repo.upsert(user_id, pair[0], pair[1])
    return pair, True


def _commit_backfill(session) -> None:
    """Persist lazy back-fill writes; a failure must never break the read."""
    try:
        session.commit()
    except Exception:
        session.rollback()


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
    cache: CacheService = Depends(get_cache_service),
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

    display_repo = UserDisplayRepository(session)
    # ONE query for all candidate names/avatars; Keycloak is touched only for
    # users missing from / stale in the snapshot, which are then back-filled.
    snapshots = display_repo.bulk_get([str(uid) for uid, _ in top])
    dirty = False

    result: list[LeaderboardEntry] = []
    rank_counter = 0
    for user_id, points in top:
        if rank_counter >= limit:
            # We've collected enough valid entries — stop iterating
            # so we don't waste lookups on the tail of the oversample.
            break
        display, wrote = _resolve_display(
            str(user_id), snapshots, idp, cache, display_repo
        )
        dirty = dirty or wrote
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
    if dirty:
        _commit_backfill(session)
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
    cache: CacheService = Depends(get_cache_service),
):
    """User's visible position on the leaderboard.

    Rank computed by replaying the same orphan-filtered iteration as
    `/leaderboard` (line 184-200) — raw `points_repo.get_user_rank`
    counts orphan user_points rows (left behind by Keycloak user
    deletions, see TECH_DEBT) and reports a rank that disagrees
    with what the top-list shows the same user as. Operator caught
    this 28.05.2026: «#1 aima 446» on the podium but «#7 aima 446»
    in the me-pill below.

    Trade-off: a Keycloak round-trip per row of the oversample.
    Hard-capped at the same `200` ceiling as the /leaderboard
    endpoint so this is bounded.
    """
    points_repo = UserPointsRepository(session)
    display_repo = UserDisplayRepository(session)
    # Enroll the caller into the leaderboard (zero-points row) if they aren't
    # already — so every registered user appears in the global Рейтинг even
    # before earning anything. Idempotent; the app hits /me on both Home and
    # Рейтинг, so this covers new registrants without a registration hook.
    points_repo.ensure_row(user.id)
    total = points_repo.get_total_points(user.id)

    # Bulk-fetch the snapshot once for the caller + the whole oversample, so the
    # orphan-filtered rank loop reads names from one SQL query instead of up to
    # 200 serial Keycloak calls.
    ranked = points_repo.get_all_ranked(200) if total > 0 else []
    snapshots = display_repo.bulk_get([str(user.id)] + [str(u) for u, _ in ranked])
    dirty = False

    own, wrote = _resolve_display(str(user.id), snapshots, idp, cache, display_repo)
    dirty = dirty or wrote
    name, raw_avatar = own if own is not None else ("Пользователь", None)

    gap_to_milestone_pts: int | None = None
    milestone: int | None = None

    if total <= 0:
        rank = 0
    else:
        target_id_str = str(user.id)
        rank = points_repo.get_user_rank(user.id)
        visible_rank = 0
        milestone_points_map: dict[int, int] = {}

        for u_id, pts in ranked:
            disp, wrote = _resolve_display(
                str(u_id), snapshots, idp, cache, display_repo
            )
            dirty = dirty or wrote
            if disp is None:
                continue
            visible_rank += 1
            # Track points at each tier milestone as we pass through them.
            # Milestones are always above the user's rank, so they appear
            # before the user in this sorted iteration.
            if visible_rank in (3, 10, 50, 100):
                milestone_points_map[visible_rank] = pts
            if str(u_id) == target_id_str:
                rank = visible_rank
                break

        milestone = _milestone_rank(rank)
        if milestone is not None and milestone in milestone_points_map:
            gap = milestone_points_map[milestone] - total
            if gap > 0:
                gap_to_milestone_pts = gap

    # Always commit: `ensure_row` above may have inserted the caller's
    # enrollment row, and `dirty` only tracks display-snapshot back-fills.
    # A commit with nothing pending is a cheap no-op.
    _commit_backfill(session)

    return MyRankEntry(
        rank=rank,
        user_id=str(user.id),
        name=name,
        avatar_url=_resolve_avatar(raw_avatar, file_service),
        total_points=total,
        milestone_rank=milestone,
        gap_to_milestone_pts=gap_to_milestone_pts,
    )


@router.get(
    "/sprint",
    response_model=SprintStatusEntry,
    summary="Статус недельного спринта (цель + текущий победитель)",
)
async def get_sprint_status(
    session: Session = Depends(get_db_session),
    idp: IdentityProviderClientKeycloak = Depends(get_identity_provider_client_keycloak),
    file_service: FileService = Depends(get_file_service),
    cache: CacheService = Depends(get_cache_service),
    lb_points_service: LeaderboardPointsService = Depends(get_leaderboard_points_service),
):
    """Public, no auth (CRM task #7 — "Еженедельный спринт"): the first
    user each week to reach the admin-configured `sprint_target_points`
    threshold is locked in as that week's winner. The lock itself
    happens inline in `UserPointsRepository.add_points` (every
    points-award path: ЕНТ full-exam, battle wins, referral/payment
    rewards) via `LeaderboardPointsService.check_and_lock_sprint_winner`
    — this endpoint only reads the result.

    Always returns 200 with this shape, never 404 — `target_points` /
    `week_start_at` / `winner` are simply null when the sprint feature
    hasn't been configured yet, so the mobile client has one shape to
    render instead of a separate "not configured" error path.

    Winner name/avatar resolution reuses the exact same user_display
    snapshot + Keycloak-fallback mechanism `GET /leaderboard` and
    `GET /leaderboard/me` already use (`_resolve_display`), not a
    second lookup.
    """
    target_points, week_start_at, winner_row = lb_points_service.get_sprint_status_raw()
    if target_points is None:
        return SprintStatusEntry(target_points=None, week_start_at=None, winner=None)

    winner: SprintWinnerDTO | None = None
    if winner_row is not None:
        winner_user_id, points_at_win, won_at = winner_row
        display_repo = UserDisplayRepository(session)
        snapshots = display_repo.bulk_get([str(winner_user_id)])
        display, wrote = _resolve_display(
            str(winner_user_id), snapshots, idp, cache, display_repo
        )
        if wrote:
            _commit_backfill(session)
        name, raw_avatar = display if display is not None else ("Пользователь", None)
        winner = SprintWinnerDTO(
            user_id=str(winner_user_id),
            name=name,
            avatar_url=_resolve_avatar(raw_avatar, file_service),
            points_at_win=points_at_win,
            won_at=won_at,
        )

    return SprintStatusEntry(
        target_points=target_points,
        week_start_at=week_start_at,
        winner=winner,
    )
