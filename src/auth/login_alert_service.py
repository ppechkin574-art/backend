"""Security push on a new login ("вход с другого устройства").

Fired after a successful login. With single-session enforcement a new login
evicts the previous device, so this push warns the user (on whatever devices
still hold a registered FCM token) that their account was just accessed
elsewhere — the "кто-то украл аккаунт" early-warning.

DORMANT until Firebase is configured in prod (`firebase__enabled=false` today):
- `enabled` short-circuits before any work, so the login path stays cheap;
- even if it were called, `FirebaseNotificationClient.send_multicast` is a no-op
  while disabled.

Token storage is reused from the daily-test push feature
(`DailyTestDeviceToken`, keyed by the user's id == Keycloak `sub`).
"""

import logging
from uuid import UUID

from sqlalchemy import select

from clients.firebase import FirebaseNotificationClient
from database import Database
from quiz.models.daily_tests import DailyTestDeviceToken

logger = logging.getLogger(__name__)


class LoginAlertService:
    _TITLE = "Вход в аккаунт"
    _BODY_DEFAULT = (
        "Выполнен вход в ваш аккаунт на другом устройстве. "
        "Если это были не вы — срочно смените пароль."
    )
    _BODY_WITH_CITY = (
        "Выполнен вход с {city}. "
        "Если это были не вы — срочно смените пароль."
    )

    def __init__(
        self,
        database: Database,
        firebase_client: FirebaseNotificationClient,
    ):
        self._database = database
        self._firebase_client = firebase_client

    @property
    def enabled(self) -> bool:
        return self._firebase_client.enabled

    def notify_new_login(
        self,
        user_id: UUID,
        city: str | None = None,
        ip: str | None = None,
    ) -> None:
        """Best-effort: must NEVER raise into the login flow."""
        if not self.enabled:
            return
        try:
            tokens = self._fetch_tokens(user_id)
            if not tokens:
                # Logged (not silent) so "push didn't arrive" is diagnosable:
                # the account simply has no FCM token registered yet — typically
                # an app build that predates token registration / the current
                # Firebase project, or notifications denied on the device.
                logger.info(
                    "auth.login.alert user=%s requested=0 (no registered device tokens)",
                    user_id,
                )
                return
            body = (
                self._BODY_WITH_CITY.format(city=city)
                if city
                else self._BODY_DEFAULT
            )
            result = self._firebase_client.send_multicast(
                tokens,
                title=self._TITLE,
                body=body,
                data={"type": "new_login", "ip": ip or "", "city": city or ""},
            )
            logger.info(
                "auth.login.alert user=%s city=%s requested=%s delivered=%s",
                user_id,
                city or "unknown",
                result.requested,
                result.success,
            )
        except Exception:
            logger.warning("auth.login.alert failed for %s", user_id, exc_info=True)

    def _fetch_tokens(self, user_id: UUID) -> list[str]:
        session = self._database.session
        try:
            rows = session.scalars(
                select(DailyTestDeviceToken.token).where(
                    DailyTestDeviceToken.student_guid == user_id
                )
            ).all()
            return [t for t in rows if t]
        finally:
            session.close()
