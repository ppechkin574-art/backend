from sqlalchemy import text
from sqlalchemy.orm import Session

from quiz.models.user_display import UserDisplay


class UserDisplayRepository:
    """Read/write the denormalized leaderboard display snapshot."""

    def __init__(self, session: Session):
        self._session = session

    def bulk_get(self, user_ids: list) -> dict:
        """Return ``{str(user_id): (name, avatar, updated_at)}`` for the given
        ids in a SINGLE query. Missing ids are simply absent from the dict."""
        if not user_ids:
            return {}
        rows = (
            self._session.query(
                UserDisplay.user_id,
                UserDisplay.name,
                UserDisplay.avatar,
                UserDisplay.updated_at,
            )
            .filter(UserDisplay.user_id.in_(user_ids))
            .all()
        )
        return {str(r[0]): (r[1], r[2], r[3]) for r in rows}

    def upsert(self, user_id, name: str, avatar: str | None) -> None:
        """Insert or refresh a user's snapshot (bumps updated_at to now())."""
        stmt = text(
            """
            INSERT INTO user_display (user_id, name, avatar, updated_at)
            VALUES (:user_id, :name, :avatar, now())
            ON CONFLICT (user_id) DO UPDATE
            SET name = EXCLUDED.name,
                avatar = EXCLUDED.avatar,
                updated_at = now()
            """
        )
        self._session.execute(
            stmt, {"user_id": str(user_id), "name": name, "avatar": avatar}
        )
