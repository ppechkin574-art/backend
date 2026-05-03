import logging
from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quiz.models.cashback import (
    CashbackDailyCompletion,
    CashbackRewardHistory,
    CashbackUserState,
)

logger = logging.getLogger(__name__)


class CashbackRepository:
    def __init__(self, session: Session):
        self._session = session

    def get_user_state(self, student_guid: UUID) -> CashbackUserState | None:
        """Получить состояние пользователя, опционально с блокировкой строки."""
        query = select(CashbackUserState).where(CashbackUserState.student_guid == student_guid)
        return self._session.execute(query).scalar_one_or_none()

    def create_user_state(self, student_guid: UUID) -> CashbackUserState:
        """Создать новое состояние (если нет)."""
        state = CashbackUserState(student_guid=student_guid)
        self._session.add(state)
        self._session.flush()
        return state

    def update_user_state(self, state: CashbackUserState) -> None:
        """Обновить существующее состояние (уже в сессии)."""
        self._session.add(state)

    def get_daily_completion(self, student_guid: UUID, completion_date: date) -> CashbackDailyCompletion | None:
        """Получить запись о завершении дня за конкретную дату."""
        return self._session.execute(
            select(CashbackDailyCompletion).where(
                CashbackDailyCompletion.student_guid == student_guid,
                CashbackDailyCompletion.completion_date == completion_date,
            )
        ).scalar_one_or_none()

    def create_daily_completion(
        self,
        student_guid: UUID,
        completion_date: date,
        streak_number: int,
        day_number: int,
        reward_earned: bool = False,
    ) -> CashbackDailyCompletion:
        """Создать запись о завершении дня."""
        daily = CashbackDailyCompletion(
            student_guid=student_guid,
            completion_date=completion_date,
            streak_number=streak_number,
            day_number=day_number,
            reward_earned=reward_earned,
        )
        self._session.add(daily)
        self._session.flush()
        return daily

    def get_last_completion(self, student_guid: UUID) -> CashbackDailyCompletion | None:
        """Получить последнюю запись о завершении дня (по дате)."""
        return self._session.execute(
            select(CashbackDailyCompletion)
            .where(CashbackDailyCompletion.student_guid == student_guid)
            .order_by(CashbackDailyCompletion.completion_date.desc())
            .limit(1)
        ).scalar_one_or_none()

    # def create_reward(self, student_guid: UUID, amount: int, streak_number: int) -> CashbackRewardHistory:
    #     """Создать запись о начислении награды."""
    #     reward = CashbackRewardHistory(student_guid=student_guid, amount=amount, streak_number=streak_number)
    #     self._session.add(reward)
    #     self._session.flush()
    #     return reward

    def get_reward_history(self, student_guid: UUID, limit: int = 100) -> list[CashbackRewardHistory]:
        """Получить историю начислений пользователя."""
        return (
            self._session.execute(
                select(CashbackRewardHistory)
                .where(CashbackRewardHistory.student_guid == student_guid)
                .order_by(CashbackRewardHistory.awarded_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )

    def get_total_earned(self, student_guid: UUID) -> int:
        """Сумма всех начислений пользователя."""
        result = self._session.execute(
            select(func.sum(CashbackRewardHistory.amount)).where(CashbackRewardHistory.student_guid == student_guid)
        ).scalar()
        return result or 0

    def get_completions_in_range(
        self, student_guid: UUID, start_date: date, end_date: date
    ) -> list[CashbackDailyCompletion]:
        return (
            self._session.query(CashbackDailyCompletion)
            .filter(
                CashbackDailyCompletion.student_guid == student_guid,
                CashbackDailyCompletion.completion_date >= start_date,
                CashbackDailyCompletion.completion_date <= end_date,
            )
            .order_by(CashbackDailyCompletion.completion_date)
            .all()
        )

    def get_rewards_for_feed(
        self, student_guid: UUID, limit: int, offset: int
    ) -> tuple[list[CashbackRewardHistory], int]:
        query = (
            self._session.query(CashbackRewardHistory)
            .filter(CashbackRewardHistory.student_guid == student_guid)
            .order_by(CashbackRewardHistory.awarded_at.desc())
        )
        total = query.count()
        items = query.offset(offset).limit(limit).all()
        return items, total
