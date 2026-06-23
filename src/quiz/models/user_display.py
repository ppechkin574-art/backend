from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class UserDisplay(Base):
    """Denormalized snapshot of a user's leaderboard display name + avatar.

    Lets the leaderboard read names/avatars from Postgres in ONE query instead
    of N per-user Keycloak Admin-API calls (/leaderboard/me did up to 200 serial
    lookups). Populated lazily from Keycloak the first time a user appears in a
    leaderboard render and refreshed when the row goes stale — see
    `api/routes/user/leaderboard.py::_resolve_display`.
    """

    __tablename__ = "user_display"

    user_id = Column(UUID(as_uuid=True), primary_key=True)
    name = Column(String(255), nullable=False)
    avatar = Column(String(512), nullable=True)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
