import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException

from auth.dtos.users import UserDTO, UserUpdateDTO
from auth.services import AuthServiceInterface
from common.enums import FeatureType, PlanType
from database import Database
from subscription.dtos import PlanFeaturesDTO, SubscriptionStatusDTO
from subscription.models import TrialHistory
from subscription.plan_repository import SubscriptionPlanRepository

logger = logging.getLogger(__name__)


def _hash_phone(phone: str) -> str:
    """Stable, non-reversible identifier for a phone number — used as
    the primary key in `trial_history` so the unhashed number doesn't
    sit in the DB. sha256 is fine here; we don't need a slow KDF
    because the input space (KZ phone numbers) is small enough that
    any hash is brute-forceable — the goal is "don't log the raw
    number to BAU storage", not "resist a targeted attacker"."""
    return hashlib.sha256(phone.encode("utf-8")).hexdigest()


class SubscriptionService:
    def __init__(
        self,
        auth_service: AuthServiceInterface,
        database: Database,
    ):
        self.auth_service = auth_service
        self._database = database
        self._plan_features_cache = {}
        self._last_cache_update = None
        self._cache_ttl = 300

    def _load_plan_features_from_db(self) -> dict[PlanType, PlanFeaturesDTO]:
        """Загрузить фичи планов из БД"""
        try:
            session = self._database.session
            try:
                plans = SubscriptionPlanRepository(session).get_active_plans()
            finally:
                session.close()
            result: dict[PlanType, PlanFeaturesDTO] = {}
            for plan in plans:
                try:
                    raw_type = (plan.plan_type or "").strip()
                    matched = next(
                        (pt for pt in PlanType if pt.value.upper() == raw_type.upper()),
                        None,
                    )
                    if matched is None:
                        logger.warning("Unknown plan type in DB: %s", raw_type)
                        continue
                    plan_type = matched

                    features = plan.features if isinstance(plan.features, dict) else {}
                    limitations = plan.limitations if isinstance(plan.limitations, dict) else {}

                    plan_dto = PlanFeaturesDTO(
                        id=plan.id,
                        plan_type=plan_type,
                        name=plan.name,
                        description=plan.description,
                        price=float(plan.price) if plan.price else 0.0,
                        original_price=(float(plan.original_price) if plan.original_price else None),
                        duration_days=plan.duration_days,
                        is_recurring=plan.is_recurring,
                        trial_days=plan.trial_days,
                        features=features,
                        limitations=limitations,
                        is_active=plan.is_active,
                        is_visible=plan.is_visible,
                        display_order=plan.display_order,
                    )

                    result[plan_type] = plan_dto
                except Exception as e:
                    logger.warning("Failed to load plan %s: %s", plan.plan_type, e)
                    continue

            return result
        except Exception as e:
            logger.exception("Error loading plan features: %s", e)
            return {}

    def _get_cached_plan_features(self) -> dict[PlanType, PlanFeaturesDTO]:
        """Получить кэшированные фичи планов"""
        now = datetime.now(UTC).timestamp()

        if (
            self._last_cache_update is None
            or now - self._last_cache_update > self._cache_ttl
            or not self._plan_features_cache
        ):
            logger.info("Updating plan features cache from DB")
            self._plan_features_cache = self._load_plan_features_from_db()
            self._last_cache_update = now

        return self._plan_features_cache

    def get_plan_features(self, plan_type: PlanType) -> PlanFeaturesDTO:
        """Получить фичи для указанного плана"""
        cached = self._get_cached_plan_features()

        if plan_type in cached:
            return cached[plan_type]

        self._plan_features_cache = self._load_plan_features_from_db()
        cached_plan = self._plan_features_cache.get(plan_type)
        if cached_plan:
            return cached_plan

        default_features = self._get_default_plan_features(plan_type)

        if not default_features:
            logger.exception("Default plan features not found for plan_type: %s", plan_type)
            default_features = self._get_default_plan_features(PlanType.FREE)

        return default_features

    def _get_default_plan_features(self, plan_type: PlanType) -> PlanFeaturesDTO:
        """Дефолтные фичи плана (если нет в БД)"""
        default_features = {
            PlanType.FREE: PlanFeaturesDTO(
                id=-1,
                plan_type=PlanType.FREE,
                name="Бесплатный",
                description="Бесплатный план с ограниченным доступом",
                price=0.0,
                original_price=None,
                duration_days=0,
                is_recurring=False,
                trial_days=0,
                features={
                    FeatureType.TOPIC_TRAINER.value: True,
                    FeatureType.TRIAL_ENT.value: True,
                    FeatureType.FULL_COURSE.value: False,
                    FeatureType.CASHBACK.value: False,
                    FeatureType.DAILY_TASKS.value: False,
                    FeatureType.AI.value: False,
                    FeatureType.INCREASING_KEF.value: False,
                    FeatureType.PARENT_ACCESS.value: False,
                },
                limitations={
                    "max_trainers_per_day": 1,
                    "max_questions_per_trainer": 10,
                },
                is_active=True,
                is_visible=True,
                display_order=1,
            ),
            PlanType.PRO: PlanFeaturesDTO(
                id=-2,
                plan_type=PlanType.PRO,
                # Brand-facing name is "Month" — enum still PRO internally
                # (see common/enums.py for why we don't rename the enum).
                name="Month",
                description="Месячная подписка с полным доступом",
                price=2000.0,
                original_price=2500.0,
                duration_days=30,
                is_recurring=True,
                trial_days=0,
                features={
                    FeatureType.TOPIC_TRAINER.value: True,
                    FeatureType.TRIAL_ENT.value: True,
                    FeatureType.FULL_COURSE.value: True,
                    FeatureType.CASHBACK.value: True,
                    FeatureType.DAILY_TASKS.value: True,
                    FeatureType.AI.value: True,
                    FeatureType.INCREASING_KEF.value: False,
                    FeatureType.PARENT_ACCESS.value: True,
                },
                limitations={
                    "max_trainers_per_day": 20,
                    "max_questions_per_trainer": 100,
                },
                is_active=True,
                is_visible=True,
                display_order=2,
            ),
        }

        return default_features.get(plan_type, default_features[PlanType.FREE])

    def refresh_subscription_status(self, user: UserDTO) -> UserDTO:
        if user.plan == PlanType.PRO and user.subscription_end and datetime.now(UTC) > user.subscription_end:
            update_data = UserUpdateDTO(plan=PlanType.FREE, subscription_end=None)
            try:
                updated_user = self.auth_service.update_user_profile(user, update_data)
                logger.warning("User %s downgraded from PRO to FREE", user.id)
                return updated_user
            except Exception as e:
                logger.exception("Failed to downgrade user %s: %s", user.id, e)
                return user
        return user

    def revoke_subscription(self, user: UserDTO) -> UserDTO:
        """Immediately strip PRO → FREE (refund / chargeback / Google REVOKED).

        Unlike `cancel_subscription` (soft — keeps access until the paid period
        ends because the user already paid for it), a revoke means the money was
        returned, so access ends now. Idempotent: no-op if already FREE.
        """
        if user.plan == PlanType.FREE:
            return user
        update_data = UserUpdateDTO(plan=PlanType.FREE, subscription_end=None)
        try:
            updated_user = self.auth_service.update_user_profile(user, update_data)
            logger.warning("User %s PRO revoked (refund/revoke) → FREE", user.id)
            return updated_user
        except Exception as e:
            logger.exception("Failed to revoke user %s: %s", user.id, e)
            return user

    async def check_subscription_status(self, user: UserDTO) -> dict:
        """Проверяет статус подписки пользователя"""
        updated_user = self.refresh_subscription_status(user)
        plan_features = self.get_plan_features(updated_user.plan)

        is_expired = False
        if updated_user.subscription_end:
            is_expired = datetime.now(UTC) > updated_user.subscription_end

        return SubscriptionStatusDTO(
            plan=updated_user.plan.value,
            plan_name=plan_features.name,
            plan_description=plan_features.description,
            is_active=updated_user.plan != PlanType.FREE,
            expires_at=(updated_user.subscription_end.isoformat() if updated_user.subscription_end else None),
            features=plan_features.features,
            limitations=plan_features.limitations,
            price=plan_features.price,
            is_expired=is_expired,
            cancelled=updated_user.subscription_cancelled,
        ).dict()

    async def get_subscription_plans(self) -> list[dict[str, Any]]:
        """Получить список доступных планов подписки"""
        cached = self._get_cached_plan_features()
        result: list[dict[str, Any]] = []

        for plan_type, features in cached.items():
            if features.is_visible:
                plan_dict = {
                    "id": features.id,
                    "type": plan_type.value,
                    "name": features.name,
                    "description": features.description,
                    "price": float(features.price) if features.price else 0.0,
                    "features": features.features,
                    "limitations": features.limitations,
                    "duration_days": features.duration_days,
                    "original_price": (float(features.original_price) if features.original_price else None),
                    "discount_percent": (
                        int((1 - features.price / features.original_price) * 100)
                        if features.original_price and features.price and features.original_price > features.price
                        else None
                    ),
                    "is_recurring": features.is_recurring,
                    "trial_days": features.trial_days,
                    "display_order": features.display_order,
                    "benefit_items": features.features.get("benefit_items") or [] if features.features else [],
                }
                result.append(plan_dict)

        return result

    # def has_access_to_feature(self, user: UserDTO, feature: FeatureType) -> bool:
    #     """Проверяет, есть ли у пользователя доступ к конкретной фиче"""
    #     updated_user = self.refresh_subscription_status(user)
    #     plan_features = self.get_plan_features(updated_user.plan)
    #     return plan_features.features.get(feature.value, False)

    async def activate_subscription(
        self,
        user: UserDTO,
        plan: PlanType,
        months: int = 1,
        expires_at: datetime | None = None,
    ) -> UserDTO:
        """Activate `plan` for `user` and persist the end date in Keycloak.

        Two modes for computing `subscription_end`:

        1. **External source-of-truth** — caller passes `expires_at` explicitly.
           This is the right path when the date is known authoritatively from
           an external system (Apple receipt's `expiresDate`, App Store
           Server Notification, FreedomPay backend confirmation). We trust
           the caller and write that date — **no stacking**.
           Restore-purchases lives here: Apple already knows when the
           subscription expires; we just mirror it. Without this branch,
           a restore call would silently add 30 days on top of remaining
           time (see `tests/unit/test_subscription_activate.py`).

        2. **Legacy compute-from-plan** — caller passes only `months` (or
           nothing). We add `plan.duration_days * months` to either:
             - `user.subscription_end` if user is already active PRO →
               stacks time (correct for "buy a second month while still
               on first"), or
             - `now()` if user is FREE → fresh subscription.

           This mode is kept for the FreedomPay webhook path, where we
           don't have an external `expires_at` — we're activating from a
           charge of a known KZT amount and assume one month per
           ~3 900 ₸.

        Caller contract: pass `expires_at` whenever an authoritative
        external date exists. Skip it only for FreedomPay-style flows
        where the duration is implied by amount paid.
        """
        try:
            plan_features = self.get_plan_features(plan)
            if plan == PlanType.PRO:
                if expires_at is not None:
                    final_expires_at = expires_at
                else:
                    if (
                        user.plan == PlanType.PRO
                        and user.subscription_end
                        and user.subscription_end > datetime.now(UTC)
                    ):
                        start_date = user.subscription_end
                    else:
                        start_date = datetime.now(UTC)
                    final_expires_at = start_date + timedelta(
                        days=plan_features.duration_days * months
                    )
                update_data = UserUpdateDTO(plan=plan, subscription_end=final_expires_at)
            else:
                update_data = UserUpdateDTO(plan=plan, subscription_end=None)

            updated_user = self.auth_service.update_user_profile(user, update_data)
            logger.info(
                "Activated %s subscription for user %s (expires=%s, mode=%s)",
                plan.value,
                user.id,
                update_data.subscription_end,
                "external" if expires_at is not None else "computed",
            )
            return updated_user

        except Exception as e:
            logger.exception("Unexpected error in activate_subscription: %s", e)
            raise HTTPException(status_code=500, detail="Internal server error") from e

    def get_available_features(self, user: UserDTO) -> dict[str, Any]:
        """Получить доступные фичи для текущего плана пользователя"""
        updated_user = self.refresh_subscription_status(user)
        plan_features = self.get_plan_features(updated_user.plan)
        return plan_features.features

    async def activate_free_trial(self, user: UserDTO) -> UserDTO:
        if user.plan != PlanType.FREE:
            raise HTTPException(status_code=400, detail="You already have an active subscription")
        if user.used_trial:
            raise HTTPException(status_code=400, detail="Free trial already used")

        # Secondary gate: phone-hash blacklist. Survives Keycloak user
        # deletion so the same number can't redeem the free trial twice
        # across account churn. user.used_trial above stays the primary
        # check (covers users without phone numbers too — web-only emails).
        if user.phone:
            phone_hash = _hash_phone(user.phone)
            session = self._database.session
            try:
                existing = session.query(TrialHistory).filter(
                    TrialHistory.phone_hash == phone_hash
                ).first()
                if existing:
                    logger.warning(
                        "Trial-history hit for phone %s (user_id=%s) — refused",
                        user.phone[:6] + "***",
                        user.id,
                    )
                    raise HTTPException(
                        status_code=400,
                        detail="Free trial already used on this phone number",
                    )
            finally:
                session.close()

        updated_user = self.auth_service.activate_free_trial(user)

        # Record the grant only AFTER auth_service succeeded — if Keycloak
        # write fails we don't want the phone-hash blacklisted on a
        # partial state.
        if user.phone:
            session = self._database.session
            try:
                session.add(TrialHistory(phone_hash=_hash_phone(user.phone)))
                session.commit()
            except Exception as e:
                # Don't fail the user-facing call just because we couldn't
                # log the hash — `used_trial` on the user record still
                # prevents the trivial second attempt. This second-line
                # defence is best-effort.
                logger.exception("Failed to record trial_history row: %s", e)
                session.rollback()
            finally:
                session.close()

        return updated_user

    async def cancel_subscription(self, user: UserDTO) -> UserDTO:
        """Soft cancel: keep PRO active until subscription_end, then auto-FREE.

        - Plan and subscription_end are NOT changed → user keeps paid time.
        - Sets subscription_cancelled=True so the UI can show "active until X,
          will not renew".
        - No-op (HTTP 400) if there is no active PRO subscription to cancel.
        - Idempotent: cancelling an already-cancelled subscription returns 400.
        """
        if user.plan == PlanType.FREE:
            raise HTTPException(
                status_code=400,
                detail="Нет активной подписки для отмены",
            )
        if user.subscription_cancelled:
            raise HTTPException(
                status_code=400,
                detail="Подписка уже отменена",
            )
        update_data = UserUpdateDTO(subscription_cancelled=True)
        updated_user = self.auth_service.update_user_profile(user, update_data)
        logger.info(
            "Subscription cancelled (soft) for user %s, period valid until %s",
            user.id,
            user.subscription_end,
        )
        return updated_user
