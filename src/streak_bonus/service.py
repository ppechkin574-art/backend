"""Business logic for the daily streak coin bonus.

End-to-end flow on the iOS side:
1. App launches → GET /user/daily-streak/status. Response carries
   `has_claimed_today`, the reward sitting on the table for today,
   and the current balance.
2. If `current_streak > 0` AND NOT `has_claimed_today`, the iOS
   home screen pops the streak modal.
3. User taps «Вернуться к предметам» → POST /user/daily-streak/claim.
   Backend writes the claim row, credits the coins to Bank, returns
   the new balance.

`current_streak` is sourced from the existing attendance pipeline
(see `quiz.utils.calculations.StreakCalculator`) — we do NOT compute
or store a separate streak. This module only owns the reward layer.
"""

import logging
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from quiz.utils.period.init import to_kz_date
from streak_bonus.dtos import (
    ClaimResultDTO,
    DailyStreakStatusDTO,
    StreakPushTemplateUpdateDTO,
    StreakRewardTierCreateDTO,
    StreakRewardTierUpdateDTO,
)
from streak_bonus.models import (
    StreakBonusClaim,
    StreakPushTemplate,
    StreakRewardTier,
)
from streak_bonus.repository import StreakBonusRepository

logger = logging.getLogger(__name__)


class StreakBonusService:
    def __init__(
        self,
        repo: StreakBonusRepository,
        bank_service,  # typed loosely to avoid quiz.uows circular import
    ):
        self.repo = repo
        self.bank_service = bank_service

    # ─── helpers ─────────────────────────────────────────────────────

    def _today_kz(self) -> "date":
        return to_kz_date(datetime.utcnow()) or datetime.utcnow().date()

    def _coins_for_streak(self, streak: int) -> int:
        """Pick the largest tier whose `min_streak <= streak` and that
        is active. Returns 0 if no tier matches (e.g. streak == 0)."""
        if streak <= 0:
            return 0
        tiers = self.repo.list_tiers(only_active=True)
        applicable = [t for t in tiers if t.min_streak <= streak]
        if not applicable:
            return 0
        return max(applicable, key=lambda t: t.min_streak).coins

    # ─── public reads ────────────────────────────────────────────────

    def get_status(self, user_id: UUID, current_streak: int) -> DailyStreakStatusDTO:
        today = self._today_kz()
        existing = self.repo.get_claim_for_date(user_id, today)
        balance = self._read_balance(user_id)

        if current_streak <= 0:
            return DailyStreakStatusDTO(
                current_streak=0,
                claim_date=None,
                has_claimed_today=False,
                reward_coins=0,
                balance=balance,
            )

        if existing is not None:
            return DailyStreakStatusDTO(
                current_streak=current_streak,
                claim_date=today,
                has_claimed_today=True,
                reward_coins=existing.coins_credited,
                balance=balance,
            )

        return DailyStreakStatusDTO(
            current_streak=current_streak,
            claim_date=today,
            has_claimed_today=False,
            reward_coins=self._coins_for_streak(current_streak),
            balance=balance,
        )

    # ─── public writes ───────────────────────────────────────────────

    def claim(self, user_id: UUID, current_streak: int) -> ClaimResultDTO:
        if current_streak <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Нет активного стрика — забирать пока нечего",
            )

        today = self._today_kz()
        existing = self.repo.get_claim_for_date(user_id, today)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Бонус за сегодня уже забран",
            )

        coins = self._coins_for_streak(current_streak)
        if coins <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Награда не настроена — обратитесь к администратору",
            )

        # DB row FIRST (source of truth — prevents re-claim) then bank
        # credit. If bank credit blows up, the claim row stays — admin
        # can manually credit later, but the user can't double-claim.
        claim = StreakBonusClaim(
            user_id=user_id,
            claim_date=today,
            streak_at_claim=current_streak,
            coins_credited=coins,
        )
        try:
            self.repo.create_claim(claim)
        except IntegrityError as e:
            self.repo.db.rollback()
            if "uq_streak_bonus_claims_user_date" in str(e.orig):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Бонус за сегодня уже забран",
                )
            raise

        try:
            self.bank_service.deposit(
                student_guid=user_id,
                amount=coins,
                description=f"Бонус за стрик ({current_streak} дн.)",
                additional_metadata={
                    "source": "daily_streak_bonus",
                    "streak": current_streak,
                    "claim_date": today.isoformat(),
                },
            )
        except Exception as e:
            logger.exception(
                "Bank deposit failed for streak claim %s (user=%s): %s",
                claim.id,
                user_id,
                e,
            )
            # Don't rollback the claim — re-issue manually if needed.
            # User sees the success modal regardless (or we surface
            # an error to the client). We'll surface the error so the
            # user is told to retry.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Не удалось зачислить монеты — попробуй позже",
            )

        new_balance = self._read_balance(user_id)
        return ClaimResultDTO(
            coins_credited=coins,
            new_balance=new_balance,
            streak_after_claim=current_streak,
        )

    # ─── admin CRUD on tiers ─────────────────────────────────────────

    def list_tiers(self):
        return self.repo.list_tiers(only_active=False)

    def get_tier(self, min_streak: int) -> StreakRewardTier:
        tier = self.repo.get_tier(min_streak)
        if tier is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Тиер для min_streak={min_streak} не найден",
            )
        return tier

    def create_tier(self, payload: StreakRewardTierCreateDTO) -> StreakRewardTier:
        try:
            return self.repo.create_tier(
                StreakRewardTier(
                    min_streak=payload.min_streak,
                    coins=payload.coins,
                    is_active=payload.is_active,
                )
            )
        except IntegrityError:
            self.repo.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Тиер для min_streak={payload.min_streak} уже существует",
            )

    def update_tier(
        self, min_streak: int, payload: StreakRewardTierUpdateDTO
    ) -> StreakRewardTier:
        tier = self.get_tier(min_streak)
        if payload.coins is not None:
            tier.coins = payload.coins
        if payload.is_active is not None:
            tier.is_active = payload.is_active
        self.repo.db.flush()
        return tier

    def delete_tier(self, min_streak: int) -> None:
        tier = self.get_tier(min_streak)
        self.repo.delete_tier(tier)

    # ─── admin push template (singleton) ─────────────────────────────

    def get_push_template(self) -> StreakPushTemplate:
        template = self.repo.get_push_template()
        if template is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "Шаблон push-уведомления не инициализирован "
                    "(должен быть посеян миграцией)"
                ),
            )
        return template

    def update_push_template(
        self, payload: StreakPushTemplateUpdateDTO
    ) -> StreakPushTemplate:
        template = self.get_push_template()
        if payload.enabled is not None:
            template.enabled = payload.enabled
        if payload.title is not None:
            template.title = payload.title
        if payload.body is not None:
            template.body = payload.body
        if payload.hours_before_reset is not None:
            template.hours_before_reset = payload.hours_before_reset
        if payload.timezone is not None:
            template.timezone = payload.timezone
        self.repo.db.flush()
        return template

    # ─── internals ───────────────────────────────────────────────────

    def _read_balance(self, user_id: UUID) -> int:
        try:
            account = self.bank_service.get_or_create_account(user_id)
            return int(account.balance or 0)
        except Exception:
            logger.exception("Failed to read bank balance for %s", user_id)
            return 0
