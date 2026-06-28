"""Admin Security / Anti-Fraud endpoints."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.dependencies import allow_only_admins, get_db_session, get_identity_provider_client_keycloak
from clients.identity_provider.client import IdentityProviderClientKeycloak
from security.service import SecurityService

router = APIRouter(
    prefix="/admin/security",
    tags=["Admin - Security"],
    dependencies=[Depends(allow_only_admins)],
)


# ------------------------------------------------------------------
# Request bodies
# ------------------------------------------------------------------


class MarkReviewedRequest(BaseModel):
    reviewed_by: str


class RestrictUserRequest(BaseModel):
    reason: str
    until: datetime | None = None


class BlockUserRequest(BaseModel):
    reason: str


# ------------------------------------------------------------------
# Overview
# ------------------------------------------------------------------


@router.get("/overview", summary="Обзор безопасности")
def get_security_overview(session: Session = Depends(get_db_session)):
    """Сводка: подозрительные события за 24ч, заблокированные аккаунты и т.д."""
    return SecurityService(session=session).get_overview()


# ------------------------------------------------------------------
# Fraud events
# ------------------------------------------------------------------


@router.get("/events", summary="Список fraud-событий")
def get_fraud_events(
    page: int = 1,
    limit: int = 25,
    status: str | None = None,
    event_type: str | None = None,
    min_risk: int | None = None,
    user_id: UUID | None = None,
    ip: str | None = None,
    device_id: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    session: Session = Depends(get_db_session),
):
    return SecurityService(session=session).get_events(
        page=page,
        limit=limit,
        status=status,
        event_type=event_type,
        min_risk=min_risk,
        user_id=user_id,
        ip=ip,
        device_id=device_id,
        from_date=from_date,
        to_date=to_date,
    )


@router.post("/events/{event_id}/mark-reviewed", summary="Отметить событие как проверенное")
def mark_event_reviewed(
    event_id: int,
    body: MarkReviewedRequest,
    session: Session = Depends(get_db_session),
):
    SecurityService(session=session).mark_event_reviewed(
        event_id=event_id,
        reviewed_by=body.reviewed_by,
    )
    return {"ok": True}


# ------------------------------------------------------------------
# Risky users
# ------------------------------------------------------------------


@router.get("/users", summary="Список рискованных пользователей")
def get_risky_users(
    page: int = 1,
    limit: int = 25,
    search: str | None = None,
    status: str | None = None,
    min_risk: int | None = None,
    session: Session = Depends(get_db_session),
):
    return SecurityService(session=session).get_risky_users(
        page=page,
        limit=limit,
        search=search,
        status=status,
        min_risk=min_risk,
    )


@router.get("/users/{user_id}", summary="Профиль риска пользователя")
def get_user_risk_profile(
    user_id: UUID,
    session: Session = Depends(get_db_session),
):
    return SecurityService(session=session).get_user_risk_profile(user_id=user_id)


@router.get("/users/{user_id}/activity", summary="Активность пользователя (fraud events)")
def get_user_activity(
    user_id: UUID,
    page: int = 1,
    limit: int = 50,
    session: Session = Depends(get_db_session),
):
    return SecurityService(session=session).get_user_activity(
        user_id=user_id,
        page=page,
        limit=limit,
    )


@router.get("/users/{user_id}/points-history", summary="История очков пользователя")
def get_user_points_history(
    user_id: UUID,
    page: int = 1,
    limit: int = 50,
    session: Session = Depends(get_db_session),
):
    return SecurityService(session=session).get_user_points_history(
        user_id=user_id,
        page=page,
        limit=limit,
    )


@router.post("/users/{user_id}/restrict", summary="Ограничить пользователя")
def restrict_user(
    user_id: UUID,
    body: RestrictUserRequest,
    session: Session = Depends(get_db_session),
):
    SecurityService(session=session).restrict_user(
        user_id=user_id,
        reason=body.reason,
        until=body.until,
    )
    return {"ok": True}


@router.post("/users/{user_id}/block", summary="Заблокировать пользователя")
def block_user(
    user_id: UUID,
    body: BlockUserRequest,
    session: Session = Depends(get_db_session),
    identity_provider: IdentityProviderClientKeycloak = Depends(get_identity_provider_client_keycloak),
):
    SecurityService(session=session, identity_provider=identity_provider).block_user(
        user_id=user_id,
        reason=body.reason,
    )
    return {"ok": True}


@router.post("/users/{user_id}/unrestrict", summary="Снять ограничения с пользователя")
def unrestrict_user(
    user_id: UUID,
    session: Session = Depends(get_db_session),
    identity_provider: IdentityProviderClientKeycloak = Depends(get_identity_provider_client_keycloak),
):
    SecurityService(session=session, identity_provider=identity_provider).unrestrict_user(user_id=user_id)
    return {"ok": True}
