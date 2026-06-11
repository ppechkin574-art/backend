from sqlalchemy import text
from sqlalchemy.orm import Session
from quiz.models.leaderboard_hidden import LeaderboardHiddenUser
from quiz.models.user_points import UserPoints


class UserPointsRepository:
    def __init__(self, session: Session):
        self._session = session

    def add_points(self, user_id, points: int) -> None:
        stmt = text("""
            INSERT INTO user_points (user_id, total_points)
            VALUES (:user_id, :points)
            ON CONFLICT (user_id) DO UPDATE
            SET total_points = user_points.total_points + :points
        """)
        self._session.execute(stmt, {"user_id": user_id, "points": points})

    def get_total_points(self, user_id) -> int:
        """Вернуть сумму баллов пользователя."""
        row = (
            self._session.query(UserPoints.total_points)
            .filter(UserPoints.user_id == user_id)
            .first()
        )
        return row[0] if row else 0

    def get_all_ranked(self, limit: int = 100) -> list[tuple]:
        """Вернуть список (user_id, total_points) отсортированный по убыванию баллов.

        Пользователи из `leaderboard_hidden_users` (admin-скрытые)
        исключаются полностью — они не попадают в рейтинг, а все, кто
        ниже, поднимаются вверх (нумерация мест считается вызывающей
        стороной уже по отфильтрованному списку, без дырок)."""
        rows = (
            self._session.query(UserPoints.user_id, UserPoints.total_points)
            .filter(
                ~UserPoints.user_id.in_(
                    self._session.query(LeaderboardHiddenUser.user_id)
                )
            )
            .order_by(UserPoints.total_points.desc())
            .limit(limit)
            .all()
        )
        return rows

    def get_user_rank(self, user_id) -> int:
        """Возвращает место пользователя в рейтинге (1 = больше всех баллов).

        Скрытые админом пользователи (`leaderboard_hidden_users`) не
        учитываются в подсчёте — место видимого пользователя не должно
        включать скрытых, сидящих выше него по очкам."""
        stmt = text("""
            SELECT COUNT(*) + 1 FROM user_points
            WHERE total_points > (SELECT total_points FROM user_points WHERE user_id = :user_id)
              AND user_id NOT IN (SELECT user_id FROM leaderboard_hidden_users)
        """)
        result = self._session.execute(stmt, {"user_id": user_id}).scalar()
        return result or 1
