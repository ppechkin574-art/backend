"""Background security event logging for login/logout events.

Creates fraud_events records enriched with IP geolocation (via ip-api.com,
free tier). All work happens in a background task so it never adds latency
to the login response.

Detectors wired here:
- brute_force: 20 failed logins in 10 min from same IP or same login identifier
- suspicious_login: successful login from a different city than last known
"""

import logging
from uuid import UUID

from database.database import Database
from security.geo_service import get_client_ip, lookup_city
from security.repository import FraudEventRepository

logger = logging.getLogger(__name__)

_BRUTE_WINDOW_SEC = 600       # 10 minutes
_BRUTE_THRESHOLD  = 20        # attempts before alert
_CITY_TTL_SEC     = 30 * 24 * 3600  # 30 days


class LoginEventLogger:
    """Logs login security events to fraud_events with geo enrichment."""

    def __init__(self, database: Database, redis=None) -> None:
        self._database = database
        self._redis = redis

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
                login_identifier=login_identifier,
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
        login_identifier: str | None = None,
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

            # Brute-force detector (failed logins only)
            if not success and self._redis and ip:
                self._detect_brute_force(repo, ip, login_identifier)

            # Suspicious-city detector (successful logins only)
            if success and user_id and self._redis:
                self._detect_suspicious_city(repo, user_id, ip, city)

            session.commit()
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Detectors
    # ------------------------------------------------------------------

    def _detect_brute_force(
        self,
        repo: FraudEventRepository,
        ip: str,
        login_identifier: str | None,
    ) -> None:
        """Increment per-IP and per-login counters; fire brute_force event once per window."""
        try:
            ip_key    = f"brute:ip:{ip}"
            ip_count  = self._redis.incr(ip_key)
            if ip_count == 1:
                self._redis.expire(ip_key, _BRUTE_WINDOW_SEC)

            login_count = 0
            if login_identifier:
                login_key   = f"brute:login:{login_identifier}"
                login_count = self._redis.incr(login_key)
                if login_count == 1:
                    self._redis.expire(login_key, _BRUTE_WINDOW_SEC)

            if ip_count >= _BRUTE_THRESHOLD or login_count >= _BRUTE_THRESHOLD:
                dedup_key = f"brute:alerted:{ip}"
                if not self._redis.exists(dedup_key):
                    self._redis.setex(dedup_key, _BRUTE_WINDOW_SEC, "1")
                    repo.log_event(
                        event_type="brute_force",
                        risk_score=90,
                        ip_address=ip,
                        reason=(
                            f"Brute force: {max(ip_count, login_count)} failed logins "
                            f"in {_BRUTE_WINDOW_SEC // 60} min from IP {ip}"
                        ),
                        metadata={
                            "ip_count": ip_count,
                            "login_count": login_count,
                            "login_identifier": login_identifier,
                        },
                    )
        except Exception:
            logger.warning("brute_force detector error", exc_info=True)

    def _detect_suspicious_city(
        self,
        repo: FraudEventRepository,
        user_id: UUID,
        ip: str | None,
        city: str | None,
    ) -> None:
        """Fire suspicious_login if user's city changed since last login."""
        if not city:
            return
        try:
            city_key  = f"city:last:{user_id}"
            raw       = self._redis.get(city_key)
            last_city = raw.decode() if raw else None

            # Always update stored city (reset TTL)
            self._redis.setex(city_key, _CITY_TTL_SEC, city)

            if last_city and last_city != city:
                repo.log_event(
                    event_type="suspicious_login",
                    risk_score=65,
                    user_id=user_id,
                    ip_address=ip,
                    reason=f"Login from new city: {city} (previous: {last_city})",
                    metadata={"prev_city": last_city, "new_city": city, "ip": ip},
                )
        except Exception:
            logger.warning("suspicious_login detector error", exc_info=True)
