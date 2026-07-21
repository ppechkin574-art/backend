import logging

from sqlalchemy import text
from sqlalchemy.orm import Session
from quiz.models.leaderboard_hidden import LeaderboardHiddenUser
from quiz.models.user_points import UserPoints

logger = logging.getLogger(__name__)


class UserPointsRepository:
    def __init__(self, session: Session):
        self._session = session

    def add_points(
        self,
        user_id,
        points: int,
        source_type: str = "unknown",
        source_id: str | None = None,
        reason: str | None = None,
    ) -> None:
        from security.models import PointsAuditLog

        points_before = self.get_total_points(user_id)

        stmt = text("""
            INSERT INTO user_points (user_id, total_points)
            VALUES (:user_id, :points)
            ON CONFLICT (user_id) DO UPDATE
            SET total_points = user_points.total_points + :points
            RETURNING total_points
        """)
        points_after = self._session.execute(
            stmt, {"user_id": user_id, "points": points}
        ).scalar()

        self._session.add(
            PointsAuditLog(
                user_id=user_id,
                points_before=points_before,
                points_after=points_before + points,
                points_delta=points,
                source_type=source_type,
                source_id=source_id,
                reason=reason,
                is_suspicious=False,
            )
        )

        # Sprint-winner check (CRM task #7) — single funnel: every
        # points-awarding path (ЕНТ full-exam completion, battle wins,
        # referral/payment rewards) calls add_points(), so hooking here
        # instead of at each of those call sites guarantees none of them
        # can drift out of sync with this check in the future. Local
        # import mirrors the existing lazy cross-package import
        # convention in this codebase (e.g.
        # api/dependencies.get_leaderboard_points_service) — avoids
        # leaderboard_points being imported at module-load time from
        # quiz.repositories. check_and_lock_sprint_winner already never
        # raises internally; the try/except here is defense-in-depth so
        # even an import-time failure can't break a points award.
        try:
            from leaderboard_points.repository import LeaderboardPointsRepository
            from leaderboard_points.service import LeaderboardPointsService

            LeaderboardPointsService(
                LeaderboardPointsRepository(self._session)
            ).check_and_lock_sprint_winner(user_id, points_after)
        except Exception:
            logger.exception(
                "Sprint-winner check failed for user %s (non-fatal, points "
                "award itself is unaffected)",
                user_id,
            )

    def ensure_row(self, user_id) -> None:
        """Enroll a user into the leaderboard with a zero-points row, if one
        doesn't exist yet.

        The global Рейтинг used to list only users who had *earned* points
        (a `user_points` row is created lazily on the first award). New /
        inactive registrants were therefore invisible. Calling this from the
        leaderboard read path (`GET /leaderboard/me`, which the app hits on
        both Home and Рейтинг) enrolls every user who opens the app, without
        a per-registration hook and without touching the hot `get_user` path.

        Idempotent — `ON CONFLICT DO NOTHING`, so a re-tap is a cheap no-op
        the PK index resolves. The caller is responsible for committing.

        `user_points.user_id` has a FK to `students.id`
        (fk_user_points_user_id_students, ON DELETE CASCADE), and a
        `students` row is only created lazily (StudentsRepository.get_or_create
        on the first ЕНТ attempt / rating). A freshly registered user has no
        `students` row yet, so we must create it first or the second INSERT
        raises a ForeignKeyViolation. `students` is just (id, rating) — a
        rating-0 row is exactly what get_or_create would have written."""
        self._session.execute(
            text(
                "INSERT INTO students (id, rating) "
                "VALUES (:uid, 0) ON CONFLICT (id) DO NOTHING"
            ),
            {"uid": user_id},
        )
        self._session.execute(
            text(
                "INSERT INTO user_points (user_id, total_points) "
                "VALUES (:uid, 0) ON CONFLICT (user_id) DO NOTHING"
            ),
            {"uid": user_id},
        )

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
            # Secondary sort on user_id makes the order among point-ties
            # deterministic. Without it, the large block of 0-point users
            # (everyone enrolled via ensure_row who hasn't scored) would
            # come back in an arbitrary order that shuffles between
            # requests — the leaderboard tail would visibly reshuffle on
            # every refresh.
            .order_by(UserPoints.total_points.desc(), UserPoints.user_id)
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
