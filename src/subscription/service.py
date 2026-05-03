import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException

from auth.dtos.users import UserDTO, UserUpdateDTO
from auth.services import AuthServiceInterface
from common.enums import FeatureType, PlanType
from subscription.dtos import PlanFeaturesDTO, SubscriptionStatusDTO
from subscription.plan_repository import SubscriptionPlanRepository

logger = logging.getLogger(__name__)


class SubscriptionService:
    def __init__(
        self,
        auth_service: AuthServiceInterface,
        plan_repository: SubscriptionPlanRepository,
    ):
        self.auth_service = auth_service
        self.plan_repository = plan_repository
        self._plan_features_cache = {}
        self._last_cache_update = None
        self._cache_ttl = 300

    def _load_plan_features_from_db(self) -> dict[PlanType, PlanFeaturesDTO]:
        """Загрузить фичи планов из БД"""
        try:
            plans = self.plan_repository.get_active_plans()
            result: dict[PlanType, PlanFeaturesDTO] = {}
            for plan in plans:
                try:
                    plan_type = PlanType(plan.plan_type)

                    features = plan.features or {}
                    limitations = plan.limitations or {}

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
                except ValueError:
                    logger.warning("Unknown plan type in DB: %s", plan.plan_type)
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

        plan = self.plan_repository.get_plan_by_type(plan_type)
        if plan:
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
                name="Pro",
                description="Профессиональный план с полным доступом",
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
                }
                result.append(plan_dict)

        return result

    # def has_access_to_feature(self, user: UserDTO, feature: FeatureType) -> bool:
    #     """Проверяет, есть ли у пользователя доступ к конкретной фиче"""
    #     updated_user = self.refresh_subscription_status(user)
    #     plan_features = self.get_plan_features(updated_user.plan)
    #     return plan_features.features.get(feature.value, False)

    async def activate_subscription(self, user: UserDTO, plan: PlanType, months: int = 1) -> UserDTO:
        try:
            plan_features = self.get_plan_features(plan)
            if plan == PlanType.PRO:
                if user.plan == PlanType.PRO and user.subscription_end and user.subscription_end > datetime.now(UTC):
                    start_date = user.subscription_end
                else:
                    start_date = datetime.now(UTC)
                expires_at = start_date + timedelta(days=plan_features.duration_days * months)
                update_data = UserUpdateDTO(plan=plan, subscription_end=expires_at)
            else:
                update_data = UserUpdateDTO(plan=plan, subscription_end=None)

            updated_user = self.auth_service.update_user_profile(user, update_data)
            logger.info("Activated %s subscription for user %s", plan.value, user.id)
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
        return self.auth_service.activate_free_trial(user)
