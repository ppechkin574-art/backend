"""Business logic for leaderboard prizes.

Public path (read-only):
- `list_active_prizes()` — drives the iOS leaderboard modal

Admin path (CRUD):
- `list_all_prizes()` / `get_one()` / `create()` / `update()` / `delete()`

Rank-uniqueness is DB-enforced (UniqueConstraint on `rank`); we
surface the IntegrityError as HTTP 409 with a friendly message so
the admin form can highlight the rank field.
"""

import logging

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from leaderboard_prizes.dtos import (
    LeaderboardPrizeCreateDTO,
    LeaderboardPrizeUpdateDTO,
)
from leaderboard_prizes.models import LeaderboardPrize
from leaderboard_prizes.repository import LeaderboardPrizeRepository

logger = logging.getLogger(__name__)


class LeaderboardPrizeService:
    def __init__(self, repo: LeaderboardPrizeRepository):
        self.repo = repo

    # ─── public reads ────────────────────────────────────────────────

    def list_active_prizes(self) -> list[LeaderboardPrize]:
        return self.repo.list_active()

    # ─── admin reads ─────────────────────────────────────────────────

    def list_all_prizes(self) -> list[LeaderboardPrize]:
        return self.repo.list_all()

    def get_one(self, prize_id: int) -> LeaderboardPrize:
        prize = self.repo.get(prize_id)
        if prize is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Приз с id={prize_id} не найден",
            )
        return prize

    # ─── admin writes ────────────────────────────────────────────────

    def create(self, payload: LeaderboardPrizeCreateDTO) -> LeaderboardPrize:
        prize = LeaderboardPrize(
            rank=payload.rank,
            icon_key=payload.icon_key,
            title=payload.title,
            description=payload.description,
            is_active=payload.is_active,
        )
        try:
            return self.repo.create(prize)
        except IntegrityError as e:
            self.repo.db.rollback()
            if "uq_leaderboard_prizes_rank" in str(e.orig):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Приз для позиции #{payload.rank} уже существует",
                )
            raise

    def update(
        self, prize_id: int, payload: LeaderboardPrizeUpdateDTO
    ) -> LeaderboardPrize:
        prize = self.get_one(prize_id)
        if payload.rank is not None:
            prize.rank = payload.rank
        if payload.icon_key is not None:
            prize.icon_key = payload.icon_key
        if payload.title is not None:
            prize.title = payload.title
        if payload.description is not None:
            prize.description = payload.description
        if payload.is_active is not None:
            prize.is_active = payload.is_active
        try:
            self.repo.db.flush()
        except IntegrityError as e:
            self.repo.db.rollback()
            if "uq_leaderboard_prizes_rank" in str(e.orig):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Приз для позиции #{payload.rank} уже существует",
                )
            raise
        return prize

    def delete(self, prize_id: int) -> None:
        prize = self.get_one(prize_id)
        self.repo.delete(prize)
