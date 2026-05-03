from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel


class CashbackConditionDetailDTO(BaseModel):
    """Детализация по конкретному условию"""

    name: str
    required: int
    actual: int
    met: bool


class CashbackTodayConditionDTO(BaseModel):
    attendance: bool
    full_ent: bool
    practice_ent: bool
    daily_test: bool
    trainers: bool

    full_ent_required: int = 1
    full_ent_actual: int = 0

    practice_ent_required: int = 2
    practice_ent_actual: int = 0

    daily_test_required: int
    daily_test_actual: int = 0

    trainers_required: int = 3
    trainers_actual: int = 0

    @property
    def conditions_list(self) -> list[CashbackConditionDetailDTO]:
        return [
            CashbackConditionDetailDTO(
                name="Посещение",
                required=1,
                actual=1 if self.attendance else 0,
                met=self.attendance,
            ),
            CashbackConditionDetailDTO(
                name="Полный ЕНТ >60%",
                required=self.full_ent_required,
                actual=self.full_ent_actual,
                met=self.full_ent,
            ),
            CashbackConditionDetailDTO(
                name="Пробники ЕНТ >60% (минимум 2)",
                required=self.practice_ent_required,
                actual=self.practice_ent_actual,
                met=self.practice_ent,
            ),
            CashbackConditionDetailDTO(
                name="Ежедневные занятия",
                required=self.daily_test_required,
                actual=self.daily_test_actual,
                met=self.daily_test,
            ),
            CashbackConditionDetailDTO(
                name="Тренажёры (>70%, минимум 3)",
                required=self.trainers_required,
                actual=self.trainers_actual,
                met=self.trainers,
            ),
        ]


class CashbackTodayDTO(BaseModel):
    """Информация о сегодняшнем дне"""

    date: date
    conditions: CashbackTodayConditionDTO
    completed_conditions: int
    total_conditions: int = 5


class CashbackDailyStatDTO(BaseModel):
    """Статистика за конкретный день (для истории по дням)"""

    date: date
    attendance: bool
    full_ent_actual: int
    practice_ent_actual: int
    daily_test_actual: int
    trainers_actual: int
    all_done: bool
    reward_earned: bool


class CashbackDailyStatsResponseDTO(BaseModel):
    """Ответ со статистикой за период"""

    stats: list[CashbackDailyStatDTO]
    total_days: int
    start_date: date
    end_date: date


class CashbackStatusDTO(BaseModel):
    """Текущий статус пользователя в системе кешбека"""

    current_streak_number: int
    current_day_in_streak: int
    days_until_reward: int
    total_streaks_completed: int
    total_cashback_earned: int
    last_completed_date: date | None


class CashbackRewardHistoryItemDTO(BaseModel):
    """Элемент истории начислений"""

    id: int
    amount: int
    awarded_at: date
    streak_number: int


class CashbackHistoryDTO(BaseModel):
    """История начислений"""

    items: list[CashbackRewardHistoryItemDTO]
    total_count: int
    total_earned: int


class CashbackActionType(StrEnum):
    ATTENDANCE = "attendance"
    FULL_ENT = "full_ent"
    PRACTICE_ENT = "practice_ent"
    DAILY_TEST = "daily_test"
    TRAINER = "trainer"
    REWARD = "reward"


class CashbackActivityItemDTO(BaseModel):
    """Одно событие в ленте активности"""

    id: str
    type: CashbackActionType
    title: str
    subtitle: str | None = None
    timestamp: datetime
    data: dict = {}
    reward_amount: int | None = None
    condition_contribution: int = 1


class CashbackActivityFeedResponseDTO(BaseModel):
    items: list[CashbackActivityItemDTO]
    total: int
    limit: int
    offset: int
