from datetime import date
from typing import Protocol
from uuid import UUID

from analytics.converters import (
    to_event_create_repository,
    to_last_payment_service,
    to_top_client_service,
)
from analytics.dtos.activity import ActivityDTO
from analytics.dtos.api_filters import PeriodEnum
from analytics.dtos.api_timing import ApiTimingSummaryDTO
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
from auth.dtos.users import UserQueryDTO
from auth.repositories.users import UserRepositoryInterface
from payments.dtos import PaymentStatus


class AnalyticServiceInterface(Protocol):
    def save_event(self, event_dto: EventCreateServiceDTO) -> None:
        raise NotImplementedError

    def get_activity(self) -> ActivityDTO:
        raise NotImplementedError

    def get_efficienty(self) -> EfficientyDTO:
        raise NotImplementedError

    def get_retention(self) -> RetentionDTO:
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


class AnalyticService:
    def __init__(self, uow: UnitOfWorkAnalytics, users: UserRepositoryInterface):
        self._uow = uow
        self._users = users

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
            top_clietns_service = []
            for client in top_clients_repo:
                user = self._users.get(UserQueryDTO(id=client.user_id))
                top_clietns_service.append(to_top_client_service(client, user))
            return top_clietns_service

    def get_payments_by_year(self) -> list[PaymentsByYearDTO]:
        with self._uow:
            return self._uow.anlytic_repo.get_payments_by_year()

    def get_payments_last(
        self, page: int, status: PaymentStatus | None, search: str | None
    ) -> list[LastPaymentServiceDTO]:
        with self._uow:
            last_payments_repo = self._uow.anlytic_repo.get_payments_last(page, status, search)
            last_payments_service = []
            for payment in last_payments_repo:
                user = self._users.get(UserQueryDTO(id=payment.user_id))
                last_payments_service.append(to_last_payment_service(payment, user))
            return last_payments_service

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
