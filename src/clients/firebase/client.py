import logging
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import firebase_admin
from firebase_admin import credentials, messaging

from clients.firebase.settings import FirebaseSettings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FirebaseSendResult:
    requested: int
    success: int
    failure: int
    invalid_tokens: list[str]


class FirebaseNotificationClient:
    """Клиент Firebase Cloud Messaging с поддержкой массивной рассылки."""

    _INVALID_TOKEN_ERRORS = {"UNREGISTERED", "INVALID_ARGUMENT", "NOT_FOUND"}

    def __init__(self, settings: FirebaseSettings):
        self._settings = settings
        self._app = None
        self._lock = threading.Lock()

        if self._settings.enabled:
            self._ensure_app()
        else:
            logger.warning("Firebase notifications are disabled via settings")

    @property
    def enabled(self) -> bool:
        return self._settings.enabled and bool(self._settings.credentials_path)

    def _ensure_app(self) -> None:
        if self._app or not self._settings.credentials_path:
            return

        with self._lock:
            if self._app:
                return

            try:
                
                # return
                cred = credentials.Certificate(self._settings.credentials_path)
            except FileNotFoundError as exc:
                logger.exception(
                    "Firebase credentials file not found: %s",
                    self._settings.credentials_path,
                )
                raise exc

            try:
                self._app = firebase_admin.get_app()
                logger.debug("Reusing existing Firebase app")
            except ValueError:
                self._app = firebase_admin.initialize_app(cred)
                logger.info("Firebase app initialized")

    def send_multicast(
        self,
        tokens: Sequence[str],
        title: str | None = None,
        body: str | None = None,
        data: dict[str, str] | None = None,
    ) -> FirebaseSendResult:
        """Отправка уведомления пачкой (размер ограничен 500)."""
        if not tokens:
            return FirebaseSendResult(0, 0, 0, [])

        if not self.enabled:
            logger.warning("Firebase client disabled, skipping multicast send")
            return FirebaseSendResult(len(tokens), 0, len(tokens), list(tokens))

        self._ensure_app()

        notification = messaging.Notification(
            title=title or self._settings.default_title,
            body=body or self._settings.default_body,
        )

        message = messaging.MulticastMessage(
            notification=notification,
            data=data or {},
            tokens=list(tokens),
        )

        response = messaging.send_each_for_multicast(message, app=self._app)
        invalid_tokens: list[str] = []

        for idx, resp in enumerate(response.responses):
            if resp.success:
                continue
            code = getattr(resp.exception, "code", "")
            if code in self._INVALID_TOKEN_ERRORS:
                invalid_tokens.append(tokens[idx])
            logger.debug("FCM error for token %s: %s", tokens[idx], code)

        logger.info(
            "FCM send result: requested=%s success=%s failure=%s invalid=%s",
            len(tokens),
            response.success_count,
            response.failure_count,
            len(invalid_tokens),
        )

        return FirebaseSendResult(
            requested=len(tokens),
            success=response.success_count,
            failure=response.failure_count,
            invalid_tokens=invalid_tokens,
        )

    def broadcast(
        self,
        tokens: Iterable[str],
        title: str | None = None,
        body: str | None = None,
        data: dict[str, str] | None = None,
    ) -> FirebaseSendResult:
        """Отправка уведомления по множеству токенов (автоматически чанкует)."""
        tokens = list(tokens)
        if not tokens:
            return FirebaseSendResult(0, 0, 0, [])

        batch_size = max(1, min(self._settings.batch_send_size, 500))
        total_requested = 0
        total_success = 0
        total_failure = 0
        invalid_tokens: list[str] = []

        for idx in range(0, len(tokens), batch_size):
            chunk = tokens[idx : idx + batch_size]
            result = self.send_multicast(chunk, title=title, body=body, data=data)
            total_requested += result.requested
            total_success += result.success
            total_failure += result.failure
            invalid_tokens.extend(result.invalid_tokens)

        return FirebaseSendResult(
            requested=total_requested,
            success=total_success,
            failure=total_failure,
            invalid_tokens=invalid_tokens,
        )
