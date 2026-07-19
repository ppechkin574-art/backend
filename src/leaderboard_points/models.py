"""Admin-configurable auto-reset schedule for leaderboard points.

Singleton table (always exactly one row, id=1) — same shape as other
single-row config tables in this codebase (see app_config). Saving the
settings from the admin panel always restarts the countdown from "now":
`last_reset_at` is stamped on every `update_settings` call, so
`next_reset_at = last_reset_at + interval_days` is simple to compute
and never surprises the operator with a reset older config would have
already triggered.

`reset_mode` picks how `next_reset_at` is computed:
- `"interval"` (default, backward-compatible) — `last_reset_at + interval_days`.
- `"weekly_monday"` — the next Monday 00:00 Asia/Almaty strictly after
  `last_reset_at`. Added for the "Еженедельный спринт" requirement
  (CRM task #6): points must reset every Monday at midnight, not on an
  arbitrary N-day cadence. `interval_days` is ignored in this mode but
  kept populated (not nulled) so switching back to "interval" restores
  the previous cadence without the operator re-entering it.
"""

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from database import Base


class LeaderboardPointsSettings(Base):
    __tablename__ = "leaderboard_points_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    auto_reset_enabled = Column(Boolean, nullable=False, server_default="false")
    reset_mode = Column(String(20), nullable=False, server_default="interval")
    interval_days = Column(Integer, nullable=False, server_default="30")
    last_reset_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    updated_by = Column(String(200), nullable=True)
