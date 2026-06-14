"""Admin-configurable policy for awarding leaderboard points (stars).

One row per activity type. All four types are seeded by migration and
cannot be created or deleted through the API — only their values can be
updated. This lets the operator adjust points behaviour from the admin
panel without a backend redeploy.

Activity types:
- ent_full      — full ҰБТ attempt (currently the only source of points)
- ent_subject   — single-subject ENT attempt (disabled by default)
- trainer       — trainer session completion (disabled by default)
- daily_test    — daily test completion (disabled by default)

Modes:
- fixed         — award ``fixed_points`` regardless of score
- score_based   — award ``int(score * score_multiplier)`` where score is
                  the number of correct answers in the attempt

Repeat modes:
- always          — every completion can earn points (current ENT behaviour)
- first_only      — only the user's very first completion earns points
- improvement_only — earn points only when the new award amount exceeds
                     the user's personal best for this activity type
"""

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, func

from database import Base


class PointsPolicy(Base):
    __tablename__ = "points_policies"

    # One row per logical activity type; admin cannot add/remove rows.
    activity_type = Column(String(30), primary_key=True)

    is_enabled = Column(Boolean, nullable=False, default=False)

    # "fixed" | "score_based"
    mode = Column(String(15), nullable=False, default="fixed")

    # Used when mode == "fixed"
    fixed_points = Column(Integer, nullable=True)

    # Used when mode == "score_based"; points = int(correct_answers * multiplier)
    score_multiplier = Column(Float, nullable=True, default=1.0)

    # Minimum percentage correct to receive any points at all (0 = no threshold)
    min_score_percent = Column(Integer, nullable=False, default=0)

    # "always" | "first_only" | "improvement_only"
    repeat_mode = Column(String(20), nullable=False, default="always")

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
