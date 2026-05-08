"""Honest user-performance metrics for the result screen.

Replaces a hardcoded "+18% за месяц / Топ 15%" badge in the Flutter
client.  All values returned here come from real database state — when
there isn't enough data to make a truthful statement, the field is
returned as null and the client falls back to a neutral encouragement
("Продолжайте в том же духе") instead of fabricating a number.

Read-only: no writes, no migrations, no changes to existing models or
services.  Implemented as a fresh route file so the existing /user/...
endpoints aren't touched.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.dependencies import get_db_session, get_user
from auth.dtos.users import UserDTO
from quiz.models.ent import EntAttempt
from quiz.models.user_points import UserPoints

router = APIRouter(prefix="/user/statistics", tags=["User - Statistics"])


class PerformanceResponse(BaseModel):
    """Either a real number or null — the client must handle both.

    `improvement_percent` — average score in the last 3 completed
    attempts vs. average score in attempts before that. Null when:
      * the user has fewer than 4 completed attempts, OR
      * the recent average is <= the prior average (we hide
        regressions instead of demotivating users).

    `percentile_top` — bucket of the user's leaderboard rank, e.g. 25
    means "in the top 25%". Null when:
      * fewer than 5 users have any points (sample too small to claim
        a percentile), OR
      * the user is below the 50% line (nobody wants to read
        "you're in the bottom 30%").

    `total_attempts` is exposed for the client's own diagnostics.
    """

    improvement_percent: int | None = None
    percentile_top: int | None = None
    total_attempts: int = 0


def _compute_improvement(session: Session, student_guid) -> int | None:
    """Recent vs. prior average score, integer percent gain. None when
    there's not enough history or the user got worse."""
    completed = (
        session.query(EntAttempt.score, EntAttempt.completed_at)
        .filter(
            EntAttempt.student_guid == student_guid,
            EntAttempt.completed_at.is_not(None),
        )
        .order_by(EntAttempt.completed_at.desc())
        .all()
    )
    if len(completed) < 4:
        return None

    recent_scores = [row[0] for row in completed[:3]]
    prior_scores = [row[0] for row in completed[3:]]
    if not prior_scores:
        return None

    recent_avg = sum(recent_scores) / len(recent_scores)
    prior_avg = sum(prior_scores) / len(prior_scores)
    if prior_avg <= 0 or recent_avg <= prior_avg:
        return None

    delta = (recent_avg - prior_avg) / prior_avg * 100
    rounded = int(round(delta))
    # Cap at 999 to keep the badge readable on the result screen
    return min(rounded, 999) if rounded > 0 else None


def _compute_percentile(session: Session, user_id) -> int | None:
    """User's rank as a percentage bucket: 10/25/50.  None if the
    population is too small or the user isn't in the top half."""
    total_users = session.query(func.count(UserPoints.user_id)).scalar() or 0
    if total_users < 5:
        return None

    user_points = (
        session.query(UserPoints.total_points)
        .filter(UserPoints.user_id == user_id)
        .scalar()
    )
    if user_points is None:
        return None

    # Number of users strictly above the current user (1-based rank)
    users_above = (
        session.query(func.count(UserPoints.user_id))
        .filter(UserPoints.total_points > user_points)
        .scalar()
        or 0
    )
    rank = users_above + 1
    raw_percentile = (rank / total_users) * 100

    if raw_percentile <= 10:
        return 10
    if raw_percentile <= 25:
        return 25
    if raw_percentile <= 50:
        return 50
    return None  # below median — don't surface the number


@router.get(
    "/performance",
    response_model=PerformanceResponse,
    summary="Improvement % and percentile bucket for the result screen",
)
def get_performance(
    user: UserDTO = Depends(get_user),
    session: Session = Depends(get_db_session),
):
    total_attempts = (
        session.query(func.count(EntAttempt.id))
        .filter(
            EntAttempt.student_guid == user.id,
            EntAttempt.completed_at.is_not(None),
        )
        .scalar()
        or 0
    )
    improvement = _compute_improvement(session, user.id)
    percentile = _compute_percentile(session, user.id)
    return PerformanceResponse(
        improvement_percent=improvement,
        percentile_top=percentile,
        total_attempts=total_attempts,
    )
