import logging
from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import HTTPException

from analytics.dtos.api_filters import PeriodEnum
from analytics.service import AnalyticServiceInterface
from api.dependencies import allow_admin_or_marketing, get_analytics_service
from payments.dtos import PaymentStatus

logger = logging.getLogger(__name__)

# Marketing surface: the «Маркетинг» dashboard reads its activity /
# retention / efficiency / revenue / top-clients data from this router,
# so it is gated by `allow_admin_or_marketing` (admins keep access;
# users with the `marketing` realm role also get in). All endpoints
# here are read-only analytics.
router = APIRouter(
    prefix="/admin/analytics",
    tags=["Admin - Analytics"],
    dependencies=[Depends(allow_admin_or_marketing)],
)


@router.get("/activity")
def get_activity(service: AnalyticServiceInterface = Depends(get_analytics_service)):
    return service.get_activity()


@router.get("/efficienty")
def get_efficienty(
    service: AnalyticServiceInterface = Depends(get_analytics_service),
):
    return service.get_efficienty()


@router.get("/retention")
def get_retention(
    service: AnalyticServiceInterface = Depends(get_analytics_service),
):
    return service.get_retention()


@router.get("/audience")
def get_audience(
    service: AnalyticServiceInterface = Depends(get_analytics_service),
):
    """Marketing-safe audience breakdown (COUNTS ONLY, no PII).

    Aggregate over ALL Keycloak users by role / plan / grade. Reachable
    by the `marketing` role too (this router is `allow_admin_or_marketing`).
    Backed by a 600s Redis cache — the underlying full Keycloak fetch is
    heavy (~1200 users)."""
    return service.get_audience()


@router.get("/payments/info")
def get_payment_statistic(
    date_from: date | None = Query(None, description="Начало периода"),
    date_to: date | None = Query(None, description="Конец периода"),
    status: PaymentStatus | None = Query(None, description="Статус платежа"),
    period: PeriodEnum | None = Query(None, description="Период"),
    service: AnalyticServiceInterface = Depends(get_analytics_service),
):
    if date_to and date_from and date_from > date_to:
        raise HTTPException(
            status_code=400,
            detail="Invalid date_from param: date_from не может быть больше date_to ",
        )

    return service.get_payments_statistic(status, period, date_from, date_to)


@router.get("/top_clients")
def get_top_clients(
    show_all: bool = Query(False, description="Показать всех"),
    service: AnalyticServiceInterface = Depends(get_analytics_service),
):
    return service.get_payments_top_clients(show_all)


@router.get("/payments/by_year")
def get_payments_by_year(
    service: AnalyticServiceInterface = Depends(get_analytics_service),
):
    return service.get_payments_by_year()


@router.get("/payments/last")
def get_payments_last(
    page: int = Query(1, ge=1, description="Номер страницы"),
    search: str | None = Query(None, description="Поиск по email"),
    status: PaymentStatus | None = Query(None, description="Статус платежа"),
    service: AnalyticServiceInterface = Depends(get_analytics_service),
):
    return service.get_payments_last(page, search, status)


@router.get("/api-timing")
def get_api_timing(
    hours: int = Query(24, ge=1, le=720, description="Окно в часах"),
    platform: str | None = Query(None, description="Фильтр по платформе (Android/iOS)"),
    app_version: str | None = Query(None, description="Фильтр по версии приложения"),
    service: AnalyticServiceInterface = Depends(get_analytics_service),
):
    """RUM: реальная задержка API с телефонов (из событий api_request)."""
    return service.get_api_timing_summary(hours, platform, app_version)


@router.get("/payments/by-gateway")
def get_payments_by_gateway(
    hours: int = Query(720, ge=1, le=8760, description="Окно в часах (по умолчанию 30 дней)"),
    service: AnalyticServiceInterface = Depends(get_analytics_service),
):
    """Выручка (paid) по шлюзам: Google Play vs FreedomPay."""
    return service.get_payments_by_gateway(hours)
