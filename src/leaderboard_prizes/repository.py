from sqlalchemy import select
from sqlalchemy.orm import Session

from leaderboard_prizes.models import LeaderboardPrize


class LeaderboardPrizeRepository:
    """Thin DB layer for the `leaderboard_prizes` table. No business
    logic — that lives in the service."""

    def __init__(self, db: Session):
        self.db = db

    def list_all(self) -> list[LeaderboardPrize]:
        """All prizes — admin view (active + inactive). Ordered by rank."""
        return list(
            self.db.scalars(
                select(LeaderboardPrize).order_by(LeaderboardPrize.rank)
            ).all()
        )

    def list_active(self) -> list[LeaderboardPrize]:
        """Public client view — only active prizes, ordered by rank."""
        return list(
            self.db.scalars(
                select(LeaderboardPrize)
                .where(LeaderboardPrize.is_active.is_(True))
                .order_by(LeaderboardPrize.rank)
            ).all()
        )

    def get(self, prize_id: int) -> LeaderboardPrize | None:
        return self.db.get(LeaderboardPrize, prize_id)

    def get_by_rank(self, rank: int) -> LeaderboardPrize | None:
        return self.db.scalars(
            select(LeaderboardPrize).where(LeaderboardPrize.rank == rank)
        ).first()

    def create(self, prize: LeaderboardPrize) -> LeaderboardPrize:
        self.db.add(prize)
        self.db.flush()
        return prize

    def delete(self, prize: LeaderboardPrize) -> None:
        self.db.delete(prize)
        self.db.flush()
