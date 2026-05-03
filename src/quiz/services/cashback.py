import logging
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from bank.service import BankService
from quiz.dtos.cashback import (
    CashbackActionType,
    CashbackActivityFeedResponseDTO,
    CashbackActivityItemDTO,
    CashbackDailyStatDTO,
    CashbackDailyStatsResponseDTO,
    CashbackHistoryDTO,
    CashbackRewardHistoryItemDTO,
    CashbackStatusDTO,
    CashbackTodayConditionDTO,
    CashbackTodayDTO,
)
from quiz.dtos.enums import ExamType
from quiz.models.cashback import CashbackUserState
from quiz.uows.uows import UnitOfWorkTests
from utils.cache import CacheService, CacheStrategy, cached

logger = logging.getLogger(__name__)


class CashbackService:
    ASTANA_OFFSET = timedelta(hours=5)
    STREAK_LENGTH = 5  # days
    MAX_STREAKS = 6  # streaks_count
    REWARD_AMOUNT = 500  # tenge

    def __init__(
        self,
        uow: UnitOfWorkTests,
        cache_service: CacheService,
        bank_service: BankService,
    ):
        self._uow = uow
        self._cache_service = cache_service
        self._bank_service = bank_service

    @staticmethod
    def _get_astana_now() -> datetime:
        utc_now = datetime.now(UTC)
        return utc_now + CashbackService.ASTANA_OFFSET

    @staticmethod
    def _get_astana_today() -> date:
        return CashbackService._get_astana_now().date()

    @staticmethod
    def _get_utc_range_for_astana_date(d: date) -> tuple[datetime, datetime]:
        start_ast = (
            datetime.combine(d, datetime.min.time(), tzinfo=UTC)
            # - CashbackService.ASTANA_OFFSET
        )
        end_ast = (
            datetime.combine(d, datetime.max.time(), tzinfo=UTC)
            # - CashbackService.ASTANA_OFFSET
        )
        # logger.info("[_get_utc_range_for_astana_date] d: %s", d)
        # logger.info(
        #     "[_get_utc_range_for_astana_date] start_ast: %s, end_ast: %s",
        #     start_ast,
        #     end_ast,
        # )
        return start_ast, end_ast

    def check_and_update(self, student_guid: UUID) -> CashbackStatusDTO | None:
        astana_today = self._get_astana_today()

        with self._uow:
            state = self._uow.cashback.get_user_state(student_guid)
            if not state:
                state = self._uow.cashback.create_user_state(student_guid)
                self._uow.commit()

        with self._uow:
            state = self._uow.cashback.get_user_state(student_guid)

            existing_today = self._uow.cashback.get_daily_completion(student_guid, astana_today)

            if existing_today:
                return self._build_status_dto(state)

            last_completion = self._uow.cashback.get_last_completion(student_guid)
            last_date = last_completion.completion_date if last_completion else None

            yesterday = astana_today - timedelta(days=1)
            if last_date and last_date < yesterday:
                state.current_streak_number = 1
                state.current_day_in_streak = 0
                state.last_completed_date = last_date

            all_done, _ = self._check_today_conditions(student_guid, astana_today)
            if not all_done:
                return self._build_status_dto(state)

            state.current_day_in_streak += 1
            state.last_completed_date = astana_today

            streak_num = state.current_streak_number
            day_num = state.current_day_in_streak

            reward_earned = False
            if day_num == self.STREAK_LENGTH:
                state.total_cashback_earned += self.REWARD_AMOUNT
                state.total_streaks_completed += 1
                reward_earned = True

                if state.current_streak_number < self.MAX_STREAKS:
                    state.current_streak_number += 1
                    state.current_day_in_streak = 0
                else:
                    state.current_streak_number = 1
                    state.current_day_in_streak = 0

            self._uow.cashback.create_daily_completion(
                student_guid=student_guid,
                completion_date=astana_today,
                streak_number=streak_num,
                day_number=day_num,
                reward_earned=reward_earned,
            )

            self._uow.cashback.update_user_state(state)
            self._uow.commit()

            if reward_earned:
                self._bank_service.deposit(
                    student_guid=student_guid,
                    amount=self.REWARD_AMOUNT,
                    description=f"Cashback for streak #{streak_num}",
                    metadata={"streak_number": streak_num},
                )

            self._invalidate_cache(student_guid)
            logger.debug("Invalidated cache for user %s", student_guid)

            logger.info(
                "User %s completed day %s of streak %s. Reward earned: %s",
                student_guid,
                day_num,
                streak_num,
                reward_earned,
            )

            return self._build_status_dto(state)

    def _check_today_conditions(self, student_guid: UUID, target_date: date) -> tuple[bool, dict]:
        start_utc, end_utc = self._get_utc_range_for_astana_date(target_date)

        attendance = self._uow.attendance.has_app_open_event(student_guid, start_utc, end_utc)

        full_ent_actual = self._uow.ent_attempts.count_full_ents_above_threshold(
            student_guid, start_utc, end_utc, threshold=60
        )
        full_ent = full_ent_actual >= 1

        practice_ent_actual = self._uow.ent_attempts.count_practice_ents_above_threshold(
            student_guid, start_utc, end_utc, threshold=60
        )
        practice_ent = practice_ent_actual >= 2

        daily_test_actual = self._uow.daily_tests.count_completed_daily_tests_in_range(student_guid, start_utc, end_utc)
        preferences = self._uow.daily_tests.get_subject_preferences(student_guid)
        daily_test_required = len(preferences) if preferences else 1
        daily_test = daily_test_actual >= daily_test_required

        trainers_actual = self._uow.trainer_attempts.count_completed_trainers_above_threshold(
            student_guid, start_utc, end_utc, threshold=70
        )
        trainers = trainers_actual >= 3

        all_done = attendance and full_ent and practice_ent and daily_test and trainers

        details = {
            "attendance": attendance,
            "full_ent": full_ent,
            "practice_ent": practice_ent,
            "daily_test": daily_test,
            "trainers": trainers,
            "full_ent_actual": full_ent_actual,
            "practice_ent_actual": practice_ent_actual,
            "daily_test_required": daily_test_required,
            "daily_test_actual": daily_test_actual,
            "trainers_actual": trainers_actual,
        }
        return all_done, details

    @cached(strategy=CacheStrategy.USER, ttl=300, resource="cashback_status")
    def get_status(self, student_guid: UUID) -> CashbackStatusDTO:
        with self._uow:
            state = self._uow.cashback.get_user_state(student_guid)
            if not state:
                logger.debug(
                    "No existing state for user %s. Returning default status",
                    student_guid,
                )
                state = CashbackUserState(
                    student_guid=student_guid,
                    current_streak_number=1,
                    current_day_in_streak=0,
                    total_streaks_completed=0,
                    total_cashback_earned=0,
                    last_completed_date=None,
                )
            return self._build_status_dto(state)

    @cached(strategy=CacheStrategy.USER, ttl=60, resource="cashback_today")
    def get_today_status(self, student_guid: UUID) -> CashbackTodayDTO:
        with self._uow:
            astana_today = self._get_astana_today()
            _, details = self._check_today_conditions(student_guid, astana_today)

            completed_conditions = sum(
                [
                    details["attendance"],
                    details["full_ent"],
                    details["practice_ent"],
                    details["daily_test"],
                    details["trainers"],
                ]
            )

            conditions_dto = CashbackTodayConditionDTO(
                attendance=details["attendance"],
                full_ent=details["full_ent"],
                practice_ent=details["practice_ent"],
                daily_test=details["daily_test"],
                trainers=details["trainers"],
                full_ent_actual=details["full_ent_actual"],
                practice_ent_actual=details["practice_ent_actual"],
                daily_test_required=details["daily_test_required"],
                daily_test_actual=details["daily_test_actual"],
                trainers_actual=details["trainers_actual"],
            )

            return CashbackTodayDTO(
                date=astana_today,
                conditions=conditions_dto,
                completed_conditions=completed_conditions,
                total_conditions=5,
            )

    @cached(strategy=CacheStrategy.USER, ttl=3600, resource="cashback_history")
    def get_history(self, student_guid: UUID, limit: int = 100) -> CashbackHistoryDTO:
        with self._uow:
            items = self._uow.cashback.get_reward_history(student_guid, limit)
            total_earned = self._uow.cashback.get_total_earned(student_guid)
            return CashbackHistoryDTO(
                items=[
                    CashbackRewardHistoryItemDTO(
                        id=item.id,
                        amount=item.amount,
                        awarded_at=item.awarded_at,
                        streak_number=item.streak_number,
                    )
                    for item in items
                ],
                total_count=len(items),
                total_earned=total_earned,
            )

    def _build_status_dto(self, state: CashbackUserState) -> CashbackStatusDTO:
        last_date = None if not state.id else state.last_completed_date

        if state.current_day_in_streak == 0:
            days_until = self.STREAK_LENGTH - 0
        else:
            days_until = self.STREAK_LENGTH - state.current_day_in_streak

        with self._uow:
            total_earned = self._uow.cashback.get_total_earned(state.student_guid) if state.id else 0

            return CashbackStatusDTO(
                current_streak_number=state.current_streak_number,
                current_day_in_streak=state.current_day_in_streak,
                days_until_reward=days_until,
                total_streaks_completed=state.total_streaks_completed,
                total_cashback_earned=total_earned,
                last_completed_date=last_date,
            )

    def _invalidate_cache(self, student_guid: UUID):
        self._cache_service.invalidate_by_resources(
            ["cashback_status", "cashback_today", "cashback_history"],
            user_id=student_guid,
        )

    def get_daily_stats(
        self,
        student_guid: UUID,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> CashbackDailyStatsResponseDTO:
        with self._uow:
            today = self._get_astana_today()
            if end_date is None:
                end_date = today
            if start_date is None:
                start_date = today - timedelta(days=30)

            completions = self._uow.cashback.get_completions_in_range(student_guid, start_date, end_date)
            completed_dates = {c.completion_date: c for c in completions}

            stats = []
            current = start_date
            while current <= end_date:
                all_done, details = self._check_today_conditions(student_guid, current)
                reward_earned = current in completed_dates and completed_dates[current].reward_earned

                stats.append(
                    CashbackDailyStatDTO(
                        date=current,
                        attendance=details["attendance"],
                        full_ent_actual=details["full_ent_actual"],
                        practice_ent_actual=details["practice_ent_actual"],
                        daily_test_actual=details["daily_test_actual"],
                        trainers_actual=details["trainers_actual"],
                        all_done=all_done,
                        reward_earned=reward_earned,
                    )
                )
                current += timedelta(days=1)

            return CashbackDailyStatsResponseDTO(
                stats=stats,
                total_days=len(stats),
                start_date=start_date,
                end_date=end_date,
            )

    def get_activity_feed(
        self, student_guid: UUID, limit: int = 50, offset: int = 0
    ) -> CashbackActivityFeedResponseDTO:
        """
        Получить ленту активности пользователя
        """
        with self._uow:
            all_items = []

            attendance_logs, _ = self._uow.attendance.get_attendance_logs_for_feed(student_guid, limit=1000, offset=0)
            for log in attendance_logs:
                all_items.append(
                    {
                        "id": f"attendance_{log.id}",
                        "type": CashbackActionType.ATTENDANCE,
                        "title": "Заход в приложение",
                        "subtitle": None,
                        "timestamp": log.activity_date,
                        "data": {},
                        "condition_contribution": 1,
                    }
                )

            ent_attempts, _ = self._uow.ent_attempts.get_ent_attempts_for_feed(student_guid, limit=1000, offset=0)
            for attempt in ent_attempts:
                stats = self._uow.ent_attempts.get_attempt_statistic(attempt.id, None)
                if not stats:
                    continue
                percentage = (stats.correct / stats.total_questions * 100) if stats.total_questions else 0
                is_full = attempt.exam_type == ExamType.full_exam
                if is_full:
                    pass
                action_type = CashbackActionType.FULL_ENT if is_full else CashbackActionType.PRACTICE_ENT

                all_items.append(
                    {
                        "id": f"ent_{attempt.id}",
                        "type": action_type,
                        "title": f"{'Полный ЕНТ' if is_full else 'Пробный ЕНТ'}",
                        "subtitle": f"Предмет: {attempt.options.subject.name if attempt.options else 'Неизвестно'}",
                        "timestamp": attempt.completed_at or attempt.started_at,
                        "data": {
                            "score": stats.score,
                            "correct": stats.correct,
                            "total": stats.total_questions,
                            "percentage": round(percentage, 1),
                            "passed": percentage > 60,
                        },
                        "condition_contribution": 1 if percentage > 60 else 0,
                    }
                )

            daily_attempts, _ = self._uow.daily_tests.get_daily_test_attempts_for_feed(
                student_guid, limit=1000, offset=0
            )
            for attempt in daily_attempts:
                total_questions = attempt.correct_answers + attempt.incorrect_answers + attempt.skipped_answers
                percentage = (attempt.correct_answers / total_questions * 100) if total_questions else 0
                all_items.append(
                    {
                        "id": f"daily_{attempt.id}",
                        "type": CashbackActionType.DAILY_TEST,
                        "title": "Ежедневный тест",
                        "subtitle": f"Предмет: {attempt.subject.name if attempt.subject else 'Смешанный'}",
                        "timestamp": attempt.completed_at,
                        "data": {
                            "score": attempt.score,
                            "correct": attempt.correct_answers,
                            "total": total_questions,
                            "percentage": round(percentage, 1),
                        },
                        "condition_contribution": 1,
                    }
                )

            trainer_attempts, _ = self._uow.trainer_attempts.get_trainer_attempts_for_feed(
                student_guid, limit=1000, offset=0
            )
            for attempt in trainer_attempts:
                stats = self._uow.trainer_attempts.get_attempt_statistic(attempt.id)
                total = stats.get("total_questions", 0)
                correct = stats.get("correct", 0)
                percentage = (correct / total * 100) if total else 0
                all_items.append(
                    {
                        "id": f"trainer_{attempt.id}",
                        "type": CashbackActionType.TRAINER,
                        "title": "Тренажёр",
                        "subtitle": f"Тема: {attempt.trainer.topic.name if attempt.trainer and attempt.trainer.topic else 'Неизвестно'}",
                        "timestamp": attempt.completed_at or attempt.started_at,
                        "data": {
                            "correct": correct,
                            "total": total,
                            "percentage": round(percentage, 1),
                            "passed": percentage > 70,
                        },
                        "condition_contribution": 1 if percentage > 70 else 0,
                    }
                )

            rewards, _ = self._uow.cashback.get_rewards_for_feed(student_guid, limit=1000, offset=0)
            for reward in rewards:
                all_items.append(
                    {
                        "id": f"reward_{reward.id}",
                        "type": CashbackActionType.REWARD,
                        "title": "Начисление кешбека",
                        "subtitle": f"Стрик #{reward.streak_number}",
                        "timestamp": reward.awarded_at,
                        "data": {},
                        "reward_amount": reward.amount,
                        "condition_contribution": 0,
                    }
                )

            all_items.sort(key=lambda x: x["timestamp"], reverse=True)

            total_all = len(all_items)

            paginated = all_items[offset : offset + limit]

            items_dto = [CashbackActivityItemDTO(**item) for item in paginated]

            return CashbackActivityFeedResponseDTO(items=items_dto, total=total_all, limit=limit, offset=offset)
