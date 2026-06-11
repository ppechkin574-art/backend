from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from analytics.converters import (
    to_event_create_repository,
    to_last_payment_service,
    to_top_client_service,
)
from analytics.dtos.activity import ActivityDTO
from analytics.dtos.api_filters import PeriodEnum
from analytics.dtos.audience import AudienceCountDTO, AudienceDTO
from analytics.dtos.api_timing import ApiTimingSummaryDTO
from analytics.dtos.payments_by_gateway import PaymentsByGatewaySummaryDTO
from analytics.dtos.efficienty import EfficientyDTO
from analytics.dtos.events import EventCreateServiceDTO
from analytics.dtos.payments import (
    LastPaymentServiceDTO,
    PaymentsByYearDTO,
    PaymentStatisticDTO,
    TopClientServiceDTO,
)
from analytics.dtos.retention import RetentionDTO
from analytics.dtos.screen_time import ScreenTimeByActivityDTO, UserScreenTimeDTO
from analytics.exceptions import WrongEventMetaData
from analytics.uow import UnitOfWorkAnalytics
from auth.repositories.users import UserRepositoryInterface
from common.enums import PlanType
from payments.dtos import PaymentStatus
from utils.cache import CacheService, CacheStrategy, cached


class AnalyticServiceInterface(Protocol):
    def save_event(self, event_dto: EventCreateServiceDTO) -> None:
        raise NotImplementedError

    def get_activity(self) -> ActivityDTO:
        raise NotImplementedError

    def get_efficienty(self) -> EfficientyDTO:
        raise NotImplementedError

    def get_retention(self) -> RetentionDTO:
        raise NotImplementedError

    def get_audience(self) -> AudienceDTO:
        raise NotImplementedError

    def get_payments_statistic(
        self,
        status: PaymentStatus | None,
        period: PeriodEnum | None,
        date_from: date | None,
        date_to: date | None,
    ) -> PaymentStatisticDTO:
        raise NotImplementedError

    def get_payments_top_clients(self, show_all: bool) -> list:
        raise NotImplementedError

    def get_payments_by_year(self) -> list:
        raise NotImplementedError

    def get_payments_last(self, page: int, status: PaymentStatus | None, search: str | None) -> list:
        raise NotImplementedError

    def get_user_screen_time(self, user_id: UUID, start_date: date, end_date: date) -> UserScreenTimeDTO:
        raise NotImplementedError

    def get_user_screen_time_by_activity(
        self, user_id: UUID, start_date: date, end_date: date
    ) -> ScreenTimeByActivityDTO:
        raise NotImplementedError

    def get_api_timing_summary(
        self,
        hours: int = 24,
        platform: str | None = None,
        app_version: str | None = None,
    ) -> ApiTimingSummaryDTO:
        raise NotImplementedError

    def get_payments_by_gateway(self, hours: int = 720) -> PaymentsByGatewaySummaryDTO:
        raise NotImplementedError


class AnalyticService:
    def __init__(
        self,
        uow: UnitOfWorkAnalytics,
        users: UserRepositoryInterface,
        cache_service: CacheService | None = None,
    ):
        self._uow = uow
        self._users = users
        # Named `_cache_service` so the @cached decorator (which looks up
        # getattr(self, "_cache_service")) can drive the audience cache.
        self._cache_service = cache_service

    def save_event(self, event_dto: EventCreateServiceDTO) -> None:
        with self._uow:
            event_repo_dto, is_valid_meta = to_event_create_repository(event_dto)
            self._uow.anlytic_repo.save_event(event_repo_dto)
            if not is_valid_meta:
                raise WrongEventMetaData

    def get_activity(self) -> ActivityDTO:
        with self._uow:
            return self._uow.anlytic_repo.get_activity()

    def get_efficienty(self) -> EfficientyDTO:
        with self._uow:
            return self._uow.anlytic_repo.get_efficienty()

    def get_retention(self) -> RetentionDTO:
        with self._uow:
            return self._uow.anlytic_repo.get_retention()

    @cached(strategy=CacheStrategy.GLOBAL, ttl=600, resource="analytics_audience")
    def get_audience(self) -> AudienceDTO:
        """Marketing-safe audience aggregate: COUNTS ONLY, no PII.

        Enumerates the ENTIRE Keycloak directory (paginated full fetch,
        ~1200 users) and buckets each user by their per-user attributes:
          - role  → `attributes.role[0]` (set at registration / admin
                    create, e.g. student / parent / teacher / admin);
                    normalised to lowercase, blank → "user".
          - plan  → `attributes.plan[0]` (FREE / PRO), upper-cased;
                    blank → FREE (mirrors to_user_dto's default).
          - grade → `attributes.grade[0]` (school class 5..11) → "N класс";
                    missing/invalid → "не указан" (legacy users before the
                    grade field shipped).

        Result is cached in Redis for 600s (@cached GLOBAL) because the
        full Keycloak fetch is heavy. Only aggregate counts leave this
        method — no usernames / emails / phones are ever returned.
        """
        idp = self._users.identity_provider_client
        users = idp.get_all_users()

        by_role: dict[str, int] = {}
        by_plan: dict[str, int] = {}
        by_grade: dict[str, int] = {}

        for u in users:
            attrs = u.attributes

            role = "user"
            if attrs and attrs.role:
                first = (attrs.role[0] or "").strip().lower()
                if first:
                    role = first
            by_role[role] = by_role.get(role, 0) + 1

            plan = PlanType.FREE.value
            if attrs and attrs.plan:
                first = (attrs.plan[0] or "").strip().upper()
                if first:
                    plan = first
            by_plan[plan] = by_plan.get(plan, 0) + 1

            grade_label = "не указан"
            if attrs and attrs.grade:
                raw = (attrs.grade[0] or "").strip()
                try:
                    parsed = int(raw)
                    if 1 <= parsed <= 11:
                        grade_label = f"{parsed} класс"
                except (ValueError, TypeError):
                    pass
            by_grade[grade_label] = by_grade.get(grade_label, 0) + 1

        def _to_counts(d: dict[str, int]) -> list[AudienceCountDTO]:
            return [
                AudienceCountDTO(name=name, count=count)
                for name, count in sorted(d.items(), key=lambda kv: kv[1], reverse=True)
            ]

        return AudienceDTO(
            total=len(users),
            by_role=_to_counts(by_role),
            by_plan=_to_counts(by_plan),
            by_grade=_to_counts(by_grade),
        )

    def get_payments_statistic(
        self,
        status: PaymentStatus | None,
        period: PeriodEnum | None,
        date_from: date | None,
        date_to: date | None,
    ) -> PaymentStatisticDTO:
        with self._uow:
            return self._uow.anlytic_repo.get_payment_statistic(status, period, date_from, date_to)

    def get_payments_top_clients(self, show_all: bool) -> list[TopClientServiceDTO]:
        with self._uow:
            top_clients_repo = self._uow.anlytic_repo.get_payments_top_clients(show_all)
            # Build the display rows from the `payments` table itself (contact =
            # email/phone carried on the repo DTO). We no longer resolve the
            # Keycloak user — the top payers are deleted there, which made the
            # list come back empty.
            return [to_top_client_service(client) for client in top_clients_repo]

    def get_payments_by_year(self) -> list[PaymentsByYearDTO]:
        with self._uow:
            return self._uow.anlytic_repo.get_payments_by_year()

    def get_payments_last(
        self, page: int, status: PaymentStatus | None, search: str | None
    ) -> list[LastPaymentServiceDTO]:
        with self._uow:
            last_payments_repo = self._uow.anlytic_repo.get_payments_last(page, status, search)
            # Contact is resolved from the `payments` table in the SQL query
            # itself — no per-row Keycloak HTTP call needed.
            return [to_last_payment_service(payment) for payment in last_payments_repo]

    def get_user_screen_time(self, user_id: UUID, start_date: date, end_date: date) -> UserScreenTimeDTO:
        with self._uow:
            return self._uow.anlytic_repo.get_user_screen_time(user_id, start_date, end_date)

    def get_user_screen_time_by_activity(
        self, user_id: UUID, start_date: date, end_date: date
    ) -> ScreenTimeByActivityDTO:
        with self._uow:
            return self._uow.anlytic_repo.get_user_screen_time_by_activity(user_id, start_date, end_date)

    def get_api_timing_summary(
        self,
        hours: int = 24,
        platform: str | None = None,
        app_version: str | None = None,
    ) -> ApiTimingSummaryDTO:
        with self._uow:
            rows = self._uow.anlytic_repo.get_api_timing_summary(hours, platform, app_version)
        return ApiTimingSummaryDTO(
            window_hours=hours,
            total_samples=sum(r.count for r in rows),
            rows=rows,
        )

    def get_payments_by_gateway(self, hours: int = 720) -> PaymentsByGatewaySummaryDTO:
        with self._uow:
            rows = self._uow.anlytic_repo.get_payments_by_gateway(hours)
        return PaymentsByGatewaySummaryDTO(
            window_hours=hours,
            total_amount=sum((r.total_amount for r in rows), start=Decimal("0")),
            rows=rows,
        )
