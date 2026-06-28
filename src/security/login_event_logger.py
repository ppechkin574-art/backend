"""Background security event logging for login/logout events.

Creates fraud_events records enriched with IP geolocation (via ip-api.com,
free tier). All work happens in a background task so it never adds latency
to the login response.

Detectors wired here:
- brute_force: 20 failed logins in 10 min from same IP or same login identifier
- suspicious_login: successful login from a different city than last known
- multi_account_device: ≥3 distinct user_ids from same device_id in 30 days
"""

import logging
from uuid import UUID

from database.database import Database
from security.geo_service import get_client_ip, lookup_city
from security.repository import FraudEventRepository

logger = logging.getLogger(__name__)

_BRUTE_WINDOW_SEC     = 600             # 10 minutes
_BRUTE_THRESHOLD      = 20             # attempts before alert
_CITY_TTL_SEC         = 30 * 24 * 3600  # 30 days
_MULTI_ACCT_WINDOW_SEC    = 30 * 24 * 3600  # 30 days
_MULTI_ACCT_THRESHOLD     = 3              # distinct user_ids per device_id
_MULTI_ACCT_DEDUP_SEC     = 24 * 3600      # alert once per day per device
_MULTI_IP_WINDOW_SEC      = 24 * 3600      # 24 hours
_MULTI_IP_THRESHOLD       = 5              # distinct user_ids per IP
_MULTI_IP_DEDUP_SEC       = 24 * 3600      # alert once per day per IP
_REFERRAL_FARM_WINDOW_SEC = 30 * 24 * 3600  # 30 days
_REFERRAL_FARM_THRESHOLD  = 3              # referrals from same device_id
_REFERRAL_FARM_DEDUP_SEC  = 24 * 3600      # alert once per day per device


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
        device_id: str | None = None,
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
                device_id=device_id,
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
        device_id: str | None = None,
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
                device_id=device_id,
                metadata={
                    "city": city,
                    "ip": ip,
                    "success": success,
                    "device_id": device_id,
                },
            )

            # Brute-force detector (failed logins only)
            if not success and self._redis and ip:
                self._detect_brute_force(repo, ip, login_identifier)

            # Suspicious-city detector (successful logins only)
            if success and user_id and self._redis:
                self._detect_suspicious_city(repo, user_id, ip, city)

            # Multi-account detector (successful login with known device_id)
            if success and user_id and device_id and self._redis:
                self._detect_multi_account(repo, session, user_id, device_id)

            # Missing device_id on authenticated login (likely a script/bot)
            if success and user_id and not device_id:
                self._detect_missing_device_id(repo, user_id)

            # Multi-account from same IP (successful logins only)
            if success and user_id and ip and self._redis:
                self._detect_multi_account_ip(repo, session, user_id, ip)

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

    def _detect_multi_account(
        self,
        repo: FraudEventRepository,
        session,
        user_id: UUID,
        device_id: str,
    ) -> None:
        """Fire multi_account_device if ≥3 distinct user_ids used the same device_id in 30 days."""
        try:
            from datetime import UTC, datetime, timedelta

            from sqlalchemy import func

            from security.models import FraudEvent

            since = datetime.now(UTC) - timedelta(seconds=_MULTI_ACCT_WINDOW_SEC)
            distinct_users = (
                session.query(func.count(func.distinct(FraudEvent.user_id)))
                .filter(
                    FraudEvent.device_id == device_id,
                    FraudEvent.user_id.isnot(None),
                    FraudEvent.created_at >= since,
                )
                .scalar()
            ) or 0

            if distinct_users < _MULTI_ACCT_THRESHOLD:
                return

            dedup_key = f"multi_acct:alerted:{device_id}"
            if self._redis.exists(dedup_key):
                return
            self._redis.setex(dedup_key, _MULTI_ACCT_DEDUP_SEC, "1")

            repo.log_event(
                event_type="multi_account_device",
                risk_score=70,
                user_id=user_id,
                device_id=device_id,
                reason=(
                    f"Device {device_id[:16]}… used by {distinct_users} different accounts "
                    f"in the last 30 days (threshold: {_MULTI_ACCT_THRESHOLD})"
                ),
                metadata={
                    "device_id": device_id,
                    "distinct_users": distinct_users,
                    "threshold": _MULTI_ACCT_THRESHOLD,
                    "window_days": 30,
                },
            )
            logger.warning(
                "multi_account_device: device=%s distinct_users=%d",
                device_id[:16], distinct_users,
            )
        except Exception:
            logger.warning("multi_account_device detector error", exc_info=True)

    def _detect_missing_device_id(
        self,
        repo: FraudEventRepository,
        user_id: UUID,
    ) -> None:
        """Fire missing_device_id when a user logs in without X-Device-Id header.
        Legitimate app clients always send this header (DeviceIdInterceptor).
        Missing header suggests a script or non-app client. Low risk (45) —
        could be old app version. Fires once per user per 24h."""
        try:
            if self._redis:
                dedup_key = f"missing_did:alerted:{user_id}"
                if self._redis.exists(dedup_key):
                    return
                self._redis.setex(dedup_key, 24 * 3600, "1")
            repo.log_event(
                event_type="missing_device_id",
                risk_score=45,
                user_id=user_id,
                reason=(
                    "Login without X-Device-Id header — may indicate script/API access "
                    "rather than the official app client"
                ),
                endpoint="/auth/login",
                method="POST",
                metadata={"has_device_id": False},
            )
        except Exception:
            logger.warning("missing_device_id detector error", exc_info=True)

    def _detect_multi_account_ip(
        self,
        repo: FraudEventRepository,
        session,
        user_id: UUID,
        ip: str,
    ) -> None:
        """Fire multi_account_ip if ≥5 distinct user_ids logged in from same IP in 24h."""
        try:
            from datetime import UTC, datetime, timedelta

            from sqlalchemy import func

            from security.models import FraudEvent

            since = datetime.now(UTC) - timedelta(seconds=_MULTI_IP_WINDOW_SEC)
            distinct_users = (
                session.query(func.count(func.distinct(FraudEvent.user_id)))
                .filter(
                    FraudEvent.ip_address == ip,
                    FraudEvent.user_id.isnot(None),
                    FraudEvent.created_at >= since,
                )
                .scalar()
            ) or 0

            if distinct_users < _MULTI_IP_THRESHOLD:
                return

            dedup_key = f"multi_ip:alerted:{ip}"
            if self._redis.exists(dedup_key):
                return
            self._redis.setex(dedup_key, _MULTI_IP_DEDUP_SEC, "1")

            repo.log_event(
                event_type="multi_account_ip",
                risk_score=60,
                user_id=user_id,
                ip_address=ip,
                reason=(
                    f"IP {ip} used by {distinct_users} different accounts "
                    f"in the last 24h (threshold: {_MULTI_IP_THRESHOLD})"
                ),
                metadata={
                    "ip": ip,
                    "distinct_users": distinct_users,
                    "threshold": _MULTI_IP_THRESHOLD,
                    "window_hours": 24,
                },
            )
            logger.warning(
                "multi_account_ip: ip=%s distinct_users=%d", ip, distinct_users,
            )
        except Exception:
            logger.warning("multi_account_ip detector error", exc_info=True)

    def log_referral_redeem(
        self,
        invitee_id: UUID,
        inviter_id: UUID,
        device_id: str | None,
        ip: str | None = None,
    ) -> None:
        """Called after a successful referral code redemption.
        Detects device_id farming (same device used for ≥3 different referrals).
        Best-effort: must NEVER raise."""
        if not device_id:
            return
        try:
            session = self._database.session
            try:
                repo = FraudEventRepository(session)
                self._detect_referral_device_farm(
                    repo, session, invitee_id, inviter_id, device_id, ip
                )
                session.commit()
            finally:
                session.close()
        except Exception:
            logger.warning(
                "log_referral_redeem failed for invitee=%s", invitee_id, exc_info=True
            )

    def _detect_referral_device_farm(
        self,
        repo: FraudEventRepository,
        session,
        invitee_id: UUID,
        inviter_id: UUID,
        device_id: str,
        ip: str | None,
    ) -> None:
        """Fire referral_device_farm if ≥3 different users redeemed referrals from same device_id."""
        try:
            from datetime import UTC, datetime, timedelta

            from sqlalchemy import func

            from security.models import FraudEvent

            since = datetime.now(UTC) - timedelta(seconds=_REFERRAL_FARM_WINDOW_SEC)
            # Count distinct invitees from this device in fraud events (login_success)
            distinct_users = (
                session.query(func.count(func.distinct(FraudEvent.user_id)))
                .filter(
                    FraudEvent.device_id == device_id,
                    FraudEvent.user_id.isnot(None),
                    FraudEvent.created_at >= since,
                )
                .scalar()
            ) or 0

            if distinct_users < _REFERRAL_FARM_THRESHOLD:
                return

            dedup_key = f"referral_farm:alerted:{device_id}"
            if self._redis and self._redis.exists(dedup_key):
                return
            if self._redis:
                self._redis.setex(dedup_key, _REFERRAL_FARM_DEDUP_SEC, "1")

            repo.log_event(
                event_type="referral_device_farm",
                risk_score=75,
                user_id=inviter_id,
                device_id=device_id,
                ip_address=ip,
                reason=(
                    f"Device {device_id[:16]}… linked to {distinct_users} accounts "
                    f"that redeemed referral codes in 30 days "
                    f"(invitee: {invitee_id})"
                ),
                metadata={
                    "device_id": device_id,
                    "distinct_users": distinct_users,
                    "threshold": _REFERRAL_FARM_THRESHOLD,
                    "invitee_id": str(invitee_id),
                    "inviter_id": str(inviter_id),
                    "window_days": 30,
                },
            )
            logger.warning(
                "referral_device_farm: device=%s distinct_users=%d inviter=%s",
                device_id[:16], distinct_users, inviter_id,
            )
        except Exception:
            logger.warning("referral_device_farm detector error", exc_info=True)
