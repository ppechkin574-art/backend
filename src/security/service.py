from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Text, cast, func
from sqlalchemy.orm import Session

from security.models import FraudEvent, PointsAuditLog, UserRiskProfile

if TYPE_CHECKING:
    from clients.identity_provider.client import IdentityProviderClientKeycloak

logger = logging.getLogger(__name__)


class SecurityService:
    def __init__(
        self,
        session: Session,
        identity_provider: IdentityProviderClientKeycloak | None = None,
    ) -> None:
        self.session = session
        self._identity_provider = identity_provider

    # ------------------------------------------------------------------
    # Overview / dashboard
    # ------------------------------------------------------------------

    def get_overview(self) -> dict:
        now = datetime.now(tz=UTC)
        since_24h = now - timedelta(hours=24)

        suspicious_users_24h = (
            self.session.query(func.count(func.distinct(FraudEvent.user_id)))
            .filter(FraudEvent.created_at >= since_24h)
            .scalar()
            or 0
        )

        suspicious_events_24h = (
            self.session.query(func.count(FraudEvent.id))
            .filter(FraudEvent.created_at >= since_24h)
            .scalar()
            or 0
        )

        blocked_accounts = (
            self.session.query(func.count(UserRiskProfile.id))
            .filter(UserRiskProfile.status == "blocked")
            .scalar()
            or 0
        )

        restricted_accounts = (
            self.session.query(func.count(UserRiskProfile.id))
            .filter(UserRiskProfile.status == "restricted")
            .scalar()
            or 0
        )

        avg_risk_raw = (
            self.session.query(func.avg(UserRiskProfile.current_risk_score)).scalar()
        )
        avg_risk_score = round(float(avg_risk_raw), 1) if avg_risk_raw is not None else 0.0

        open_events = (
            self.session.query(func.count(FraudEvent.id))
            .filter(FraudEvent.status == "open")
            .scalar()
            or 0
        )

        suspicious_points_24h = (
            self.session.query(func.count(PointsAuditLog.id))
            .filter(
                PointsAuditLog.is_suspicious.is_(True),
                PointsAuditLog.created_at >= since_24h,
            )
            .scalar()
            or 0
        )

        return {
            "suspicious_users_24h": suspicious_users_24h,
            "suspicious_events_24h": suspicious_events_24h,
            "blocked_accounts": blocked_accounts,
            "restricted_accounts": restricted_accounts,
            "avg_risk_score": avg_risk_score,
            "open_events": open_events,
            "suspicious_points_24h": suspicious_points_24h,
        }

    # ------------------------------------------------------------------
    # Fraud events
    # ------------------------------------------------------------------

    def get_events(
        self,
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
    ) -> dict:
        q = self.session.query(FraudEvent)

        if status is not None:
            q = q.filter(FraudEvent.status == status)
        if event_type is not None:
            q = q.filter(FraudEvent.event_type == event_type)
        if min_risk is not None:
            q = q.filter(FraudEvent.risk_score >= min_risk)
        if user_id is not None:
            q = q.filter(FraudEvent.user_id == user_id)
        if ip is not None:
            q = q.filter(FraudEvent.ip_address == ip)
        if device_id is not None:
            q = q.filter(FraudEvent.device_id == device_id)
        if from_date is not None:
            q = q.filter(FraudEvent.created_at >= from_date)
        if to_date is not None:
            q = q.filter(FraudEvent.created_at <= to_date)

        total = q.count()
        events = q.order_by(FraudEvent.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

        return {
            "items": [self._fraud_event_to_dict(e) for e in events],
            "total": total,
            "page": page,
            "limit": limit,
        }

    # ------------------------------------------------------------------
    # Risky users
    # ------------------------------------------------------------------

    def get_risky_users(
        self,
        page: int = 1,
        limit: int = 25,
        search: str | None = None,
        status: str | None = None,
        min_risk: int | None = None,
    ) -> dict:
        q = self.session.query(UserRiskProfile)

        if status is not None:
            q = q.filter(UserRiskProfile.status == status)
        if min_risk is not None:
            q = q.filter(UserRiskProfile.current_risk_score >= min_risk)
        if search is not None:
            # search by user_id (cast to text for ILIKE)
            q = q.filter(cast(UserRiskProfile.user_id, Text).like(f"%{search}%"))

        total = q.count()
        profiles = (
            q.order_by(UserRiskProfile.current_risk_score.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )

        return {
            "items": [self._risk_profile_to_dict(p) for p in profiles],
            "total": total,
        }

    def get_user_risk_profile(self, user_id: UUID) -> dict:
        profile = (
            self.session.query(UserRiskProfile)
            .filter(UserRiskProfile.user_id == user_id)
            .first()
        )
        if profile is None:
            profile = UserRiskProfile(user_id=user_id)
            self.session.add(profile)
            self.session.commit()
            self.session.refresh(profile)
        return self._risk_profile_to_dict(profile)

    # ------------------------------------------------------------------
    # User activity / points history
    # ------------------------------------------------------------------

    def get_user_activity(
        self,
        user_id: UUID,
        page: int = 1,
        limit: int = 50,
    ) -> dict:
        q = self.session.query(FraudEvent).filter(FraudEvent.user_id == user_id)
        total = q.count()
        events = (
            q.order_by(FraudEvent.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return {
            "items": [self._fraud_event_to_dict(e) for e in events],
            "total": total,
        }

    def get_user_points_history(
        self,
        user_id: UUID,
        page: int = 1,
        limit: int = 50,
    ) -> dict:
        q = self.session.query(PointsAuditLog).filter(PointsAuditLog.user_id == user_id)
        total = q.count()
        logs = (
            q.order_by(PointsAuditLog.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return {
            "items": [self._audit_log_to_dict(log) for log in logs],
            "total": total,
        }

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def mark_event_reviewed(self, event_id: int, reviewed_by: str) -> None:
        event = self.session.query(FraudEvent).filter(FraudEvent.id == event_id).first()
        if event is not None:
            event.status = "reviewed"
            event.reviewed_at = datetime.now(tz=UTC)
            event.reviewed_by = reviewed_by
            self.session.commit()

    def restrict_user(
        self,
        user_id: UUID,
        reason: str,
        until: datetime | None = None,
    ) -> None:
        profile = self._get_or_create_profile(user_id)
        profile.status = "restricted"
        profile.restriction_reason = reason
        profile.restricted_until = until
        profile.updated_at = datetime.now(tz=UTC)
        self.session.commit()

    def block_user(self, user_id: UUID, reason: str) -> None:
        profile = self._get_or_create_profile(user_id)
        profile.status = "blocked"
        profile.blocked_at = datetime.now(tz=UTC)
        profile.restriction_reason = reason
        profile.updated_at = datetime.now(tz=UTC)
        self.session.commit()
        if self._identity_provider is not None:
            try:
                self._identity_provider.set_active(user_id, False)
            except Exception:
                logger.exception("Failed to disable Keycloak account for user %s", user_id)

    def unrestrict_user(self, user_id: UUID) -> None:
        profile = self._get_or_create_profile(user_id)
        was_blocked = profile.status == "blocked"
        profile.status = "normal"
        profile.restricted_until = None
        profile.restriction_reason = None
        profile.updated_at = datetime.now(tz=UTC)
        self.session.commit()
        if was_blocked and self._identity_provider is not None:
            try:
                self._identity_provider.set_active(user_id, True)
            except Exception:
                logger.exception("Failed to re-enable Keycloak account for user %s", user_id)

    def set_watchlist(self, user_id: UUID, watchlisted: bool, admin_username: str) -> None:
        profile = self._get_or_create_profile(user_id)
        profile.is_watchlisted = watchlisted
        profile.updated_at = datetime.now(tz=UTC)
        action = "watchlist_add" if watchlisted else "watchlist_remove"
        self._log_admin_action(user_id, action, admin_username)
        self.session.commit()

    def set_points_frozen(self, user_id: UUID, frozen: bool, admin_username: str) -> None:
        profile = self._get_or_create_profile(user_id)
        profile.points_frozen = frozen
        profile.updated_at = datetime.now(tz=UTC)
        action = "points_freeze" if frozen else "points_unfreeze"
        self._log_admin_action(user_id, action, admin_username)
        self.session.commit()

    def set_referral_disabled(self, user_id: UUID, disabled: bool, admin_username: str) -> None:
        profile = self._get_or_create_profile(user_id)
        profile.referral_disabled = disabled
        profile.updated_at = datetime.now(tz=UTC)
        action = "referral_disable" if disabled else "referral_enable"
        self._log_admin_action(user_id, action, admin_username)
        self.session.commit()

    def reset_risk_score(self, user_id: UUID, admin_username: str) -> None:
        profile = self._get_or_create_profile(user_id)
        profile.current_risk_score = 0
        profile.total_suspicious_events = 0
        profile.updated_at = datetime.now(tz=UTC)
        self._log_admin_action(user_id, "reset_risk_score", admin_username)
        self.session.commit()

    def mark_event_false_positive(self, event_id: int, reviewed_by: str) -> None:
        event = self.session.query(FraudEvent).filter(FraudEvent.id == event_id).first()
        if event is not None:
            event.status = "false_positive"
            event.reviewed_at = datetime.now(tz=UTC)
            event.reviewed_by = reviewed_by
            self.session.commit()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _log_admin_action(self, user_id: UUID, action: str, admin_username: str) -> None:
        event = FraudEvent(
            user_id=user_id,
            event_type="admin_action",
            risk_score=0,
            reason=f"Admin action: {action} by {admin_username}",
            status="reviewed",
            reviewed_at=datetime.now(tz=UTC),
            reviewed_by=admin_username,
            event_metadata={"action": action, "admin": admin_username},
        )
        self.session.add(event)

    def _get_or_create_profile(self, user_id: UUID) -> UserRiskProfile:
        profile = (
            self.session.query(UserRiskProfile)
            .filter(UserRiskProfile.user_id == user_id)
            .first()
        )
        if profile is None:
            profile = UserRiskProfile(user_id=user_id)
            self.session.add(profile)
            self.session.flush()
        return profile

    @staticmethod
    def _fraud_event_to_dict(event: FraudEvent) -> dict:
        return {
            "id": event.id,
            "user_id": str(event.user_id) if event.user_id else None,
            "device_id": event.device_id,
            "ip_address": event.ip_address,
            "endpoint": event.endpoint,
            "method": event.method,
            "user_agent": event.user_agent,
            "event_type": event.event_type,
            "reason": event.reason,
            "risk_score": event.risk_score,
            "metadata": event.event_metadata,
            "status": event.status,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "reviewed_at": event.reviewed_at.isoformat() if event.reviewed_at else None,
            "reviewed_by": event.reviewed_by,
        }

    @staticmethod
    def _risk_profile_to_dict(profile: UserRiskProfile) -> dict:
        return {
            "id": profile.id,
            "user_id": str(profile.user_id) if profile.user_id else None,
            "current_risk_score": profile.current_risk_score,
            "status": profile.status,
            "last_suspicious_activity_at": (
                profile.last_suspicious_activity_at.isoformat()
                if profile.last_suspicious_activity_at
                else None
            ),
            "total_suspicious_events": profile.total_suspicious_events,
            "restricted_until": (
                profile.restricted_until.isoformat() if profile.restricted_until else None
            ),
            "blocked_at": profile.blocked_at.isoformat() if profile.blocked_at else None,
            "restriction_reason": profile.restriction_reason,
            "is_watchlisted": profile.is_watchlisted,
            "points_frozen": profile.points_frozen,
            "referral_disabled": profile.referral_disabled,
            "created_at": profile.created_at.isoformat() if profile.created_at else None,
            "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
        }

    @staticmethod
    def _audit_log_to_dict(log: PointsAuditLog) -> dict:
        return {
            "id": log.id,
            "user_id": str(log.user_id) if log.user_id else None,
            "points_before": log.points_before,
            "points_after": log.points_after,
            "points_delta": log.points_delta,
            "source_type": log.source_type,
            "source_id": log.source_id,
            "reason": log.reason,
            "is_suspicious": log.is_suspicious,
            "fraud_event_id": log.fraud_event_id,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
