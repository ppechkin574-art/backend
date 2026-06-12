from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from security.models import FraudEvent, UserRiskProfile


class FraudEventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def log_event(
        self,
        event_type: str,
        risk_score: int,
        user_id: UUID | None = None,
        reason: str | None = None,
        ip_address: str | None = None,
        device_id: str | None = None,
        endpoint: str | None = None,
        method: str | None = None,
        user_agent: str | None = None,
        metadata: dict | None = None,
    ) -> FraudEvent:
        event = FraudEvent(
            user_id=user_id,
            event_type=event_type,
            risk_score=risk_score,
            reason=reason,
            ip_address=ip_address,
            device_id=device_id,
            endpoint=endpoint,
            method=method,
            user_agent=user_agent,
            event_metadata=metadata or {},
        )
        self._session.add(event)
        self._session.flush()

        if user_id is not None:
            self._bump_risk_profile(user_id, risk_score)

        return event

    def _bump_risk_profile(self, user_id: UUID, risk_score: int) -> None:
        profile = (
            self._session.query(UserRiskProfile)
            .filter(UserRiskProfile.user_id == user_id)
            .first()
        )
        if profile is None:
            profile = UserRiskProfile(user_id=user_id)
            self._session.add(profile)
            self._session.flush()

        now = datetime.now(tz=UTC)
        profile.total_suspicious_events = (profile.total_suspicious_events or 0) + 1
        profile.last_suspicious_activity_at = now
        # Each event contributes risk_score // 10 points (min 1), capped at 100
        profile.current_risk_score = min(
            100,
            (profile.current_risk_score or 0) + max(1, risk_score // 10),
        )
        profile.updated_at = now
