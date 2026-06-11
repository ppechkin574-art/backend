"""Admin-controlled hide-list for the in-app leaderboard.

Each row marks one Keycloak user as HIDDEN from the public leaderboard.
A hidden user is excluded from the ranking entirely — everyone below
them shifts up one place (no gaps in positions 1, 2, 3…). Because the
top-3 podium prizes are purely display-by-rank (no separate prize/claim
logic), excluding a hidden user from the ranking also removes them from
any prize.

`user_id` matches `user_points.user_id` EXACTLY — Postgres UUID
(`postgresql.UUID(as_uuid=True)`) — so the NOT IN / NOT EXISTS filter in
`UserPointsRepository` compares like-for-like with no casts.

Additive only: no FK into/out of this table (Keycloak user deletions are
not cascaded into Postgres anywhere — see the orphan handling in the
leaderboard route), no relationships, no builtin-shadowing names.
"""

from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from database import Base


class LeaderboardHiddenUser(Base):
    __tablename__ = "leaderboard_hidden_users"

    # Same column type as user_points.user_id (Keycloak user id).
    user_id = Column(UUID(as_uuid=True), primary_key=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<LeaderboardHiddenUser {self.user_id}>"
