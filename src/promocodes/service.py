import logging
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from auth.dtos.users import UserDTO
from common.enums import PlanType
from promocodes.dtos import (
    PromocodeActivationResultDTO,
    PromocodeCreateDTO,
    PromocodeDTO,
    PromocodeStatsDTO,
    PromocodeUsageDTO,
    PromocodeUsageStatsDTO,
)
from promocodes.models import Promocode, PromocodeUsage
from subscription.service import SubscriptionService

logger = logging.getLogger(__name__)


class PromocodeService:
    def __init__(self, db_session: Session, subscription_service: SubscriptionService):
        self.db_session = db_session
        self.subscription_service = subscription_service

    async def validate_promocode(self, code: str) -> Promocode:
        """Проверить промокод"""
        code = code.upper().strip()

        promocode = self.db_session.query(Promocode).filter(Promocode.code == code).first()

        if not promocode:
            raise HTTPException(status_code=404, detail="Промокод не найден")

        if promocode.expires_at and promocode.expires_at < datetime.now(UTC):
            raise HTTPException(status_code=400, detail="Промокод истек")

        if promocode.activations_count >= promocode.max_activations:
            raise HTTPException(
                status_code=400,
                detail="Промокод уже использован максимальное количество раз",
            )

        return promocode

    async def check_promocode_usage(self, user_id: str, promocode_id: int) -> bool:
        """Проверить, использовал ли пользователь уже этот промокод"""
        usage = (
            self.db_session.query(PromocodeUsage)
            .filter(
                PromocodeUsage.student_guid == str(user_id),
                PromocodeUsage.promocode_id == promocode_id,
            )
            .first()
        )

        return usage is not None

    async def get_promocode_activation_info(self, user: UserDTO, code: str) -> PromocodeActivationResultDTO:
        """Получить информацию о промокоде без его применения (временно)"""

        if user is None:
            raise HTTPException(status_code=400, detail="User is required")

        if not hasattr(user, "id") or user.id is None:
            raise HTTPException(status_code=400, detail="User ID is missing")

        promocode = await self.validate_promocode(code)

        if promocode is None:
            raise HTTPException(status_code=404, detail="Промокод не найден")

        if not promocode.is_reusable:
            user_id_str = str(user.id)
            already_used = await self.check_promocode_usage(user_id_str, promocode.id)
            if already_used:
                raise HTTPException(status_code=400, detail="Вы уже использовали этот промокод")

        try:
            plan = PlanType(promocode.plan_type)
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный тип плана в промокоде")

        # Calculate expires_at based on current time + duration
        expires_at = datetime.now(UTC) + timedelta(days=promocode.duration_days)

        return PromocodeActivationResultDTO(
            success=True,
            message=f"Промокод доступен! Активирует подписку {plan.value} на {promocode.duration_days} дней",
            plan=plan.value,
            duration_days=promocode.duration_days,
            expires_at=expires_at.isoformat(),
            is_trial=promocode.is_trial if promocode.is_trial is not None else False,
            promocode_id=promocode.id,
            usage_id=None,
        )

    # not used (temporary)
    # async def apply_promocode(self, user: UserDTO, code: str) -> PromocodeActivationResultDTO:
    #     """Применить промокод и вернуть DTO результата"""
    #     promocode = await self.validate_promocode(code)

    #     if not promocode.is_reusable:
    #         already_used = await self.check_promocode_usage(user.id, promocode.id)
    #         if already_used:
    #             raise HTTPException(status_code=400, detail="Вы уже использовали этот промокод")

    #     try:
    #         plan = PlanType(promocode.plan_type)
    #     except ValueError:
    #         raise HTTPException(status_code=400, detail="Неверный тип плана в промокоде")

    #     months = max(1, promocode.duration_days // 30)
    #     updated_user = await self.subscription_service.activate_subscription(user, plan, months)

    #     usage = PromocodeUsage(
    #         promocode_id=promocode.id,
    #         student_guid=user.id,
    #         activated_plan=plan.value,
    #         access_expires_at=datetime.now(UTC) + timedelta(days=promocode.duration_days),
    #     )

    #     promocode.activations_count += 1

    #     subscription = Subscription(
    #         user_id=user.id,
    #         plan=plan.value,
    #         status="active",
    #         started_at=datetime.now(UTC),
    #         expires_at=datetime.now(UTC) + timedelta(days=promocode.duration_days),
    #         notes=f"Активировано промокодом: {promocode.code}",
    #     )

    #     self.db_session.add(usage)
    #     self.db_session.add(subscription)
    #     self.db_session.commit()

    #     return PromocodeActivationResultDTO(
    #         success=True,
    #         message=f"Промокод успешно применен! Активирована подписка {plan.value} на {promocode.duration_days} дней",
    #         plan=plan.value,
    #         duration_days=promocode.duration_days,
    #         expires_at=(updated_user.subscription_end.isoformat() if updated_user.subscription_end else None),
    #         is_trial=promocode.is_trial,
    #         promocode_id=promocode.id,
    #         usage_id=usage.id,
    #     )

    async def create_promocode(self, create_dto: PromocodeCreateDTO) -> PromocodeDTO:
        """Создать новый промокод"""
        existing = self.db_session.query(Promocode).filter(Promocode.code == create_dto.code.upper()).first()

        if existing:
            raise HTTPException(status_code=400, detail="Промокод с таким кодом уже существует")

        # Calculate expires_at if not provided: use duration_days from now
        expires_at = create_dto.expires_at
        if expires_at is None:
            now = datetime.now(UTC)
            expires_at = now + timedelta(days=create_dto.duration_days)
        else:
            # Ensure timezone awareness if provided
            expires_at = expires_at.replace(tzinfo=UTC) if expires_at.tzinfo is None else expires_at.astimezone(UTC)

        promocode = Promocode(
            code=create_dto.code.upper(),
            description=create_dto.description,
            plan_type=create_dto.plan_type.value,
            duration_days=create_dto.duration_days,
            max_activations=create_dto.max_activations,
            expires_at=expires_at,
            created_by=create_dto.created_by,
            is_trial=create_dto.is_trial if create_dto.is_trial is not None else False,
            is_reusable=(create_dto.is_reusable if create_dto.is_reusable is not None else False),
        )

        self.db_session.add(promocode)
        self.db_session.commit()
        self.db_session.refresh(promocode)

        return PromocodeDTO(
            id=promocode.id,
            code=promocode.code,
            description=promocode.description,
            plan_type=promocode.plan_type,
            duration_days=promocode.duration_days,
            max_activations=promocode.max_activations,
            activations_count=promocode.activations_count,
            expires_at=(promocode.expires_at.isoformat() if promocode.expires_at else None),
            created_by=promocode.created_by,
            created_at=promocode.created_at.isoformat(),
            is_trial=promocode.is_trial,
            is_reusable=promocode.is_reusable,
        )

    async def get_promocode_stats(self, code: str) -> PromocodeStatsDTO:
        """Получить статистику по промокоду"""
        promocode = await self.validate_promocode(code)

        usages = self.db_session.query(PromocodeUsage).filter(PromocodeUsage.promocode_id == promocode.id).all()

        usage_dtos = [
            PromocodeUsageStatsDTO(
                id=usage.id,
                user_id=usage.student_guid,
                activated_at=usage.activated_at.isoformat(),
                expires_at=usage.access_expires_at.isoformat(),
                plan=usage.activated_plan,
            )
            for usage in usages
        ]

        return PromocodeStatsDTO(
            id=promocode.id,
            code=promocode.code,
            description=promocode.description,
            plan_type=promocode.plan_type,
            duration_days=promocode.duration_days,
            max_activations=promocode.max_activations,
            activations_count=promocode.activations_count,
            expires_at=(promocode.expires_at.isoformat() if promocode.expires_at else None),
            created_by=promocode.created_by,
            created_at=promocode.created_at.isoformat(),
            is_trial=promocode.is_trial,
            is_reusable=promocode.is_reusable,
            usage_stats={
                "total_usages": len(usage_dtos),
                "active_usages": len([u for u in usages if u.access_expires_at > datetime.now(UTC)]),
                "usages_left": promocode.max_activations - promocode.activations_count,
            },
            usages=usage_dtos,
        )

    async def get_available_promocodes(self) -> list[PromocodeDTO]:
        """Получить список доступных промокодов"""
        now = datetime.now(UTC)

        promocodes = (
            self.db_session.query(Promocode)
            .filter(
                (Promocode.expires_at > now) | (Promocode.expires_at.is_(None)),
                Promocode.activations_count < Promocode.max_activations,
            )
            .all()
        )

        return [
            PromocodeDTO(
                id=promocode.id,
                code=promocode.code,
                description=promocode.description,
                plan_type=promocode.plan_type,
                duration_days=promocode.duration_days,
                max_activations=promocode.max_activations,
                activations_count=promocode.activations_count,
                expires_at=(promocode.expires_at.isoformat() if promocode.expires_at else None),
                created_by=promocode.created_by,
                created_at=promocode.created_at.isoformat(),
                is_trial=promocode.is_trial,
                is_reusable=promocode.is_reusable,
            )
            for promocode in promocodes
        ]

    async def get_promocode_by_id(self, promocode_id: int) -> PromocodeDTO | None:
        """Получить промокод по ID"""
        promocode = self.db_session.query(Promocode).filter(Promocode.id == promocode_id).first()

        if not promocode:
            return None

        return PromocodeDTO(
            id=promocode.id,
            code=promocode.code,
            description=promocode.description,
            plan_type=promocode.plan_type,
            duration_days=promocode.duration_days,
            max_activations=promocode.max_activations,
            activations_count=promocode.activations_count,
            expires_at=(promocode.expires_at.isoformat() if promocode.expires_at else None),
            created_by=promocode.created_by,
            created_at=promocode.created_at.isoformat(),
            is_trial=promocode.is_trial,
            is_reusable=promocode.is_reusable,
        )

    async def update_promocode(self, promocode_id: int, update_data: dict) -> PromocodeDTO | None:
        """Обновить промокод"""
        promocode = self.db_session.query(Promocode).filter(Promocode.id == promocode_id).first()

        if not promocode:
            return None

        for key, value in update_data.items():
            if hasattr(promocode, key):
                setattr(promocode, key, value)

        self.db_session.commit()
        self.db_session.refresh(promocode)

        return await self.get_promocode_by_id(promocode_id)

    # async def deactivate_promocode(self, promocode_id: int) -> bool:
    #     """Деактивировать промокод"""
    #     promocode = self.db_session.query(Promocode).filter(Promocode.id == promocode_id).first()

    #     if not promocode:
    #         return False

    #     promocode.expires_at = datetime.now(UTC)
    #     self.db_session.commit()

    #     return True

    async def get_user_promocode_history(self, user_id: str) -> list[PromocodeUsageDTO]:
        """Получить историю активаций промокодов пользователем"""
        usages = (
            self.db_session.query(PromocodeUsage)
            .filter(PromocodeUsage.student_guid == str(user_id))
            .order_by(PromocodeUsage.activated_at.desc())
            .all()
        )

        result = []
        for usage in usages:
            promocode = self.db_session.query(Promocode).filter(Promocode.id == usage.promocode_id).first()

            result.append(
                PromocodeUsageDTO(
                    id=usage.id,
                    promocode_id=usage.promocode_id,
                    promocode_code=promocode.code if promocode else "Unknown",
                    user_id=usage.student_guid,
                    activated_at=usage.activated_at.isoformat(),
                    expires_at=usage.access_expires_at.isoformat(),
                    activated_plan=usage.activated_plan,
                    is_active=usage.access_expires_at > datetime.now(UTC),
                )
            )

        return result

    # async def get_promocode_usage_stats(self, promocode_id: int) -> dict[str, Any]:
    #     """Получить статистику использования промокода"""
    #     promocode = self.db_session.query(Promocode).filter(Promocode.id == promocode_id).first()

    #     if not promocode:
    #         raise HTTPException(status_code=404, detail="Промокод не найден")

    #     usages = self.db_session.query(PromocodeUsage).filter(PromocodeUsage.promocode_id == promocode_id).all()

    #     now = datetime.now(UTC)

    #     return {
    #         "total_activations": promocode.activations_count,
    #         "max_activations": promocode.max_activations,
    #         "activations_left": promocode.max_activations - promocode.activations_count,
    #         "active_usages": len([u for u in usages if u.access_expires_at > now]),
    #         "expired_usages": len([u for u in usages if u.access_expires_at <= now]),
    #         "plan_type": promocode.plan_type,
    #         "duration_days": promocode.duration_days,
    #         "is_trial": promocode.is_trial,
    #         "expires_at": (promocode.expires_at.isoformat() if promocode.expires_at else None),
    #     }

    async def deactivate_promocode_by_code(self, code: str) -> bool:
        """Деактивировать промокод по коду"""
        promocode = self.db_session.query(Promocode).filter(Promocode.code == code.upper()).first()

        if not promocode:
            return False

        promocode.expires_at = datetime.now(UTC) - timedelta(days=1)
        self.db_session.commit()

        return True

    # async def get_promocodes_by_plan(self, plan_type: PlanType) -> list[PromocodeDTO]:
    #     """Получить промокоды для определенного плана"""
    #     promocodes = self.db_session.query(Promocode).filter(Promocode.plan_type == plan_type.value).all()

    #     return [
    #         PromocodeDTO(
    #             id=p.id,
    #             code=p.code,
    #             description=p.description,
    #             plan_type=p.plan_type,
    #             duration_days=p.duration_days,
    #             max_activations=p.max_activations,
    #             activations_count=p.activations_count,
    #             expires_at=p.expires_at.isoformat() if p.expires_at else None,
    #             created_by=p.created_by,
    #             created_at=p.created_at.isoformat(),
    #             is_trial=p.is_trial,
    #             is_reusable=p.is_reusable,
    #         )
    #         for p in promocodes
    #     ]
