"""Leaderboard prizes — what users see in the «top-3 receives» modal.

One row per leaderboard rank (top-1, top-2, top-3 …). Operator
edits via the admin panel: icon (from a fixed preset of glossy SVG
assets shipped in the iOS bundle), title, free-form description.
Client renders these in the leaderboard screen so when the user
taps the gift bubble under a top-N avatar, the modal shows the
configured prize details — and motivates them to climb to that
rank themselves.

Why a separate table (not just app_settings): each row has THREE
columns of structured content (icon_key + title + description) and
multiple rows per logical entity (one per rank). Stuffing that into
key/value would mean parsing JSON or a synthetic key naming
convention — both noisier than a real table.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from database import Base


class LeaderboardPrize(Base):
    __tablename__ = "leaderboard_prizes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 1-based leaderboard position (1 = 1st place). UNIQUE so the
    # admin form can't accidentally create two rows for «top-1» — the
    # DB rejects the second insert instead of silently letting the
    # client render whichever row was last fetched.
    rank = Column(Integer, nullable=False)
    # Maps to an SVG asset key on the iOS client. See
    # `assets/grand/icons/prizes/` — the operator picks from a dropdown
    # populated by `PRIZE_ICON_KEYS` in the DTO module.
    icon_key = Column(String(32), nullable=False)
    title = Column(String(120), nullable=False)
    description = Column(Text, nullable=False, server_default="")
    # Soft-disable lets the operator hide a prize without deleting its
    # history; client filters by is_active=True.
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (UniqueConstraint("rank", name="uq_leaderboard_prizes_rank"),)
