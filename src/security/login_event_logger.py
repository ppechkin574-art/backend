"""Background security event logging for login/logout events.

Creates fraud_events records enriched with IP geolocation (via ip-api.com,
free tier). All work happens in a background task so it never adds latency
to the login response.
"""

import logging
from uuid import UUID

from database.database import Database
from security.geo_service import get_client_ip, lookup_city
from security.repository import FraudEventRepository

logger = logging.getLogger(__name__)


class LoginEventLogger:
    """Logs login security events to fraud_events with geo enrichment."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def log_login(
        self,
        user_id: UUID,
        ip: str | None,
        user_agent: str | None,
        success: bool = True,
    ) -> None:
        """Best-effort: must NEVER raise. Called from a background task."""
        try:
            city = lookup_city(ip)
            self._write_event(
                user_id=user_id,
                ip=ip,
                city=city,
                user_agent=user_agent,
                success=success,
            )
            logger.info(
                "security.login_event user=%s ip=%s city=%s success=%s",
                user_id, ip, city, success,
            )
        except Exception:
            logger.warning(
                "security.login_event failed for user=%s", user_id, exc_info=True
            )

    def log_failed_login(
        self,
        login_identifier: str,
        ip: str | None,
        user_agent: str | None,
    ) -> None:
        """Log a failed login attempt (no user_id available)."""
        try:
            city = lookup_city(ip)
            self._write_event(
                user_id=None,
                ip=ip,
                city=city,
                user_agent=user_agent,
                success=False,
                reason=f"Failed login attempt for: {login_identifier}",
            )
        except Exception:
            logger.warning("security.login_event.failed write error", exc_info=True)

    def _write_event(
        self,
        user_id: UUID | None,
        ip: str | None,
        city: str | None,
        user_agent: str | None,
        success: bool,
        reason: str | None = None,
    ) -> None:
        session = self._database.session
        try:
            repo = FraudEventRepository(session)
            event_type = "login_success" if success else "login_failed"
            repo.log_event(
                event_type=event_type,
                risk_score=0 if success else 20,
                user_id=user_id,
                reason=reason or (f"Login from {city}" if city else "Login"),
                endpoint="/auth/login",
                method="POST",
                ip_address=ip,
                user_agent=user_agent,
                metadata={
                    "city": city,
                    "ip": ip,
                    "success": success,
                },
            )
            session.commit()
        finally:
            session.close()
