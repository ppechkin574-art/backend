from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from redis import Redis
from sqlalchemy.orm import Session

from api.dependencies import get_db_session, get_redis, get_user
from auth.dtos import UserDTO
from battle.models import BattleSession
from battle.schemas import (
    BotFinishRequest,
    BotFinishResponse,
    DailyLeaderboardEntry,
    DailyLeaderboardResponse,
    JoinQueueRequest,
    JoinQueueResponse,
    SessionStatusResponse,
)
from battle.service import BattleService
from common.enums import PlanType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/battle", tags=["Battle"])


def _require_subscription(user: UserDTO) -> None:
    if getattr(user, "plan", PlanType.FREE) == PlanType.FREE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Для баттла нужна активная подписка",
        )


@router.post("/queue/join", response_model=JoinQueueResponse)
def join_queue(
    body: JoinQueueRequest,
    user: UserDTO = Depends(get_user),
    db: Session = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
):
    """Join matchmaking queue. Returns session_id immediately.
    Poll GET /battle/session/{session_id} to detect when opponent is found.
    """
    if not body.subject_ids or len(body.subject_ids) > 2:
        raise HTTPException(status_code=400, detail="Provide 1 or 2 subject_ids")

    _require_subscription(user)

    svc = BattleService(db, redis)
    return svc.join_or_create(user.id, body.subject_ids)


@router.get("/session/{session_id}", response_model=SessionStatusResponse)
def get_session(
    session_id: str,
    user: UserDTO = Depends(get_user),
    db: Session = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
):
    """Poll this endpoint to check when battle session becomes active."""
    svc = BattleService(db, redis)
    session = svc.get_session(session_id, user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Auto-activate bot session after 5 seconds of searching
    if session.is_bot and session.status == "searching":
        created = session.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        elapsed = (datetime.now(UTC) - created).total_seconds()
        if elapsed >= 5:
            activated = svc.activate_bot_session(session_id)
            if activated:
                session = activated

    opponent_name = session.bot_name
    return SessionStatusResponse(
        session_id=str(session.id),
        status=session.status,
        opponent_name=opponent_name,
        is_bot=session.is_bot,
        started_at=session.started_at,
    )


@router.delete("/session/{session_id}")
def cancel_session(
    session_id: str,
    user: UserDTO = Depends(get_user),
    db: Session = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
):
    """Cancel a searching session or forfeit an active one."""
    svc = BattleService(db, redis)
    session = svc.get_session(session_id, user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status == "searching":
        session.status = "abandoned"
        db.commit()
        # Remove from queue
        queue_key = f"battle:queue:{':'.join(str(s) for s in sorted(session.subject_ids))}"
        raw = redis.lrange(queue_key, 0, -1)
        for entry in raw:
            entry_str = entry.decode() if isinstance(entry, bytes) else entry
            import json
            parsed = json.loads(entry_str)
            if parsed.get("session_id") == session_id:
                redis.lrem(queue_key, 1, entry)
                break
    elif session.status == "active":
        svc.forfeit(session, user.id)
    return {"ok": True}


@router.get("/leaderboard/daily", response_model=DailyLeaderboardResponse)
def daily_leaderboard(
    user: UserDTO = Depends(get_user),
    db: Session = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
):
    """Daily battle leaderboard (top 100 by stars earned today in Almaty timezone)."""
    svc = BattleService(db, redis)
    data = svc.get_daily_leaderboard(my_user_id=user.id)

    # Resolve display names from user_id
    # For MVP: use user_id as name. TODO: resolve via Keycloak
    entries = [
        DailyLeaderboardEntry(
            rank=e["rank"],
            user_id=e["user_id"],
            name=e["name"],
            stars_today=e["stars_today"],
            wins=e["wins"],
            losses=e["losses"],
        )
        for e in data["entries"]
    ]

    my_raw = data.get("my_entry")
    my_entry = DailyLeaderboardEntry(**my_raw) if my_raw else None

    return DailyLeaderboardResponse(
        date=data["date"],
        entries=entries,
        my_entry=my_entry,
    )


@router.get("/session/{session_id}/bot-questions")
def get_bot_questions(
    session_id: str,
    lang: str = "ru",
    user: UserDTO = Depends(get_user),
    db: Session = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
):
    """Return questions with correct_variant_id for locally-simulated bot battles."""
    svc = BattleService(db, redis)
    session = svc.get_session(session_id, user.id)
    if not session or not session.is_bot:
        raise HTTPException(status_code=404, detail="Bot session not found")
    if session.status not in ("active", "finished"):
        raise HTTPException(status_code=400, detail="Session not active")

    questions = []
    for q in session.question_data.get("questions", []):
        text = q.get(f"text_{lang}") or q.get("text_ru") or ""
        if not text:
            continue
        expl = q.get(f"explanation_{lang}") or q.get("explanation_ru") or q.get("explanation") or ""
        variants = [
            {"id": v["id"], "text": v.get(f"text_{lang}") or v.get("text_ru") or ""}
            for v in q.get("variants", [])
        ]
        questions.append({
            "id": q["id"],
            "subject_name": q.get("subject_name", ""),
            "text": text,
            "variants": variants,
            "correct_variant_id": q.get("correct_variant_id"),
            "explanation": expl,
            "image_url": q.get("image_url"),
        })
    return {"questions": questions}


@router.post("/bot-finish/{session_id}", response_model=BotFinishResponse)
def finish_bot_session(
    session_id: str,
    body: BotFinishRequest,
    user: UserDTO = Depends(get_user),
    db: Session = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
):
    """Record result of a locally-simulated bot battle and credit stars."""
    svc = BattleService(db, redis)
    session = svc.get_session(session_id, user.id)
    if not session or not session.is_bot:
        raise HTTPException(status_code=404, detail="Bot session not found")
    if session.status == "finished":
        return BotFinishResponse(stars_earned=session.stars_player1)
    if session.status != "active":
        raise HTTPException(status_code=400, detail="Session not active")
    session.player1_score = body.player1_score
    session.player2_score = body.player2_score
    svc.finish_session(session)
    return BotFinishResponse(stars_earned=session.stars_player1)
