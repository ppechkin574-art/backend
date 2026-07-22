"""One-shot (re-runnable) admin endpoint that enrolls EVERY registered
Keycloak user into the global leaderboard with a zero-points row.

Why this exists
---------------
The global Рейтинг used to list only users who had *earned* points — a
`user_points` row is created lazily on the first award. Newly-registered
and never-scored users were therefore invisible in the leaderboard. The
read path now self-enrolls a caller on `GET /leaderboard/me`
(`UserPointsRepository.ensure_row`), but that only covers users who open
the app after the change ships. This endpoint back-fills everyone who
already exists so the leaderboard is complete immediately.

It runs INSIDE the app (unlike the `scripts/` one-offs that juggle a raw
`DATABASE_URL`), so it works on whichever host the backend lives on and
reuses the exact display-name logic the leaderboard render uses — no
divergence between back-filled and live-resolved names.

Idempotent: only users missing a `user_points` row are touched, and the
row inserts are `ON CONFLICT DO NOTHING`. Safe to re-run any time (e.g.
after a burst of new sign-ups) to top up the enrollment.
"""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.dependencies import (
    allow_read_or_admin_write,
    get_db_session,
    get_identity_provider_client_keycloak,
)
from api.routes.user.leaderboard import _safe_display_name
from clients.identity_provider.client import IdentityProviderClientKeycloak
from quiz.repositories.user_display import UserDisplayRepository
from quiz.repositories.user_points import UserPointsRepository

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/leaderboard",
    tags=["admin"],
    dependencies=[Depends(allow_read_or_admin_write)],
)

# Flush enrollment in batches so a huge realm never builds one giant
# uncommitted transaction (and partial progress survives an interruption).
_COMMIT_EVERY = 200


class BackfillEnrollmentResult(BaseModel):
    keycloak_users: int
    already_enrolled: int
    newly_enrolled: int
    display_warmed: int


@router.post(
    "/backfill-enrollment",
    response_model=BackfillEnrollmentResult,
    summary="Записать всех зарегистрированных юзеров в лидерборд с 0 баллов",
)
def backfill_enrollment(
    session: Session = Depends(get_db_session),
    idp: IdentityProviderClientKeycloak = Depends(get_identity_provider_client_keycloak),
):
    """Enroll every Keycloak user into the leaderboard at 0 points.

    Heavy but rare: enumerates the whole realm (one-time admin action),
    then for each user missing a `user_points` row creates the
    `students` + `user_points` rows (`ensure_row`) and warms the
    `user_display` snapshot from the Keycloak attributes we already
    fetched — so the first leaderboard render after the back-fill stays
    pure-SQL instead of firing a burst of per-user Keycloak lookups.
    """
    kc_users = idp.get_all_users()

    # Everyone who already has a leaderboard row — skip them so a re-run
    # only touches genuinely new users (and the counts are accurate).
    existing = {
        str(uid)
        for (uid,) in session.execute(text("SELECT user_id FROM user_points")).all()
    }

    points_repo = UserPointsRepository(session)
    display_repo = UserDisplayRepository(session)

    newly_enrolled = 0
    display_warmed = 0
    pending = 0

    for u in kc_users:
        uid = str(u.id)
        if uid in existing:
            continue
        points_repo.ensure_row(u.id)
        newly_enrolled += 1

        # Warm the display snapshot from the attributes get_all_users already
        # returned. Mirrors `_user_display_pair`: name attribute, then the
        # PII-safe fallback; avatar attribute as-is.
        name = ""
        if u.attributes and u.attributes.name:
            name = u.attributes.name[0] or ""
        avatar = None
        if u.attributes and u.attributes.avatar:
            avatar = u.attributes.avatar[0] or None
        display_repo.upsert(u.id, _safe_display_name(name, uid), avatar)
        display_warmed += 1

        pending += 1
        if pending >= _COMMIT_EVERY:
            session.commit()
            pending = 0

    if pending:
        session.commit()

    logger.info(
        "Leaderboard backfill: %d KC users, %d already enrolled, %d newly enrolled",
        len(kc_users),
        len(existing),
        newly_enrolled,
    )
    return BackfillEnrollmentResult(
        keycloak_users=len(kc_users),
        already_enrolled=len(existing),
        newly_enrolled=newly_enrolled,
        display_warmed=display_warmed,
    )
