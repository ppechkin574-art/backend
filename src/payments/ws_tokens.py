import json
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from redis import Redis

logger = logging.getLogger(__name__)


class WebSocketTokenManager:
    def __init__(self, redis: Redis, token_ttl: int = 300):
        """
        Инициализация менеджера токенов для WebSocket

        Args:
            redis: Redis клиент
            token_ttl: Время жизни токена в секундах (по умолчанию 5 минут)
        """
        self.redis = redis
        self.token_ttl = token_ttl
        self.token_prefix = "ws_token:"  # noqa S105

    def create_ws_token(
        self,
        user_id: str,
        order_id: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> str:
        """
        Создает одноразовый токен для WebSocket соединения

        Args:
            user_id: ID пользователя
            order_id: ID заказа
            ip_address: IP адрес клиента (для логирования)
            user_agent: User-Agent клиента

        Returns:
            Сгенерированный токен
        """
        token = secrets.token_urlsafe(32)
        token_key = f"{self.token_prefix}{token}"

        token_data = {
            "token_id": str(uuid.uuid4()),
            "user_id": str(user_id),
            "order_id": str(order_id),
            "created_at": datetime.now(UTC).isoformat(),
            "expires_at": (datetime.now(UTC) + timedelta(seconds=self.token_ttl)).isoformat(),
            "ip_address": ip_address,
            "user_agent": user_agent,
            "type": "ws_payment",
            "used": False,
            "use_count": 0,
            "max_uses": 10,
        }

        try:
            self.redis.setex(token_key, self.token_ttl, json.dumps(token_data, ensure_ascii=False))

            order_tokens_key = f"order_tokens:{order_id}"
            self.redis.sadd(order_tokens_key, token)
            self.redis.expire(order_tokens_key, self.token_ttl)

            logger.info(
                "Created WS token for user %s, order %s, token: %s...",
                user_id,
                order_id,
                token[:8],
            )
            return token

        except Exception as e:
            logger.exception("Failed to create WS token: %s", str(e))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create WebSocket token",
            )

    def verify_ws_token(self, token: str, order_id: str | None = None, increment_use: bool = True) -> dict[str, Any]:
        """
        Проверяет и возвращает данные WebSocket токена

        Args:
            token: Токен для проверки
            order_id: Ожидаемый order_id (опционально)
            increment_use: Увеличивать счетчик использования

        Returns:
            Данные токена

        Raises:
            HTTPException: Если токен невалиден
        """
        token_key = f"{self.token_prefix}{token}"

        try:
            token_data_json = self.redis.get(token_key)
            if not token_data_json:
                logger.warning("Token not found or expired: %s...", token[:8])
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token expired or invalid",
                )

            token_data = json.loads(token_data_json)

            if token_data.get("type") != "ws_payment":
                logger.warning("Invalid token type: %s...", token_data.get("type"))
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token type",
                )

            expires_at = datetime.fromisoformat(token_data["expires_at"])
            if datetime.now(UTC) > expires_at:
                logger.warning("Token expired: %s...", token[:8])
                self.redis.delete(token_key)
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")

            if order_id and token_data.get("order_id") != str(order_id):
                logger.warning(
                    "Token order mismatch: %s != %s",
                    token_data.get("order_id"),
                    order_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Token not valid for this order",
                )

            max_uses = token_data.get("max_uses", 10)
            use_count = token_data.get("use_count", 0)

            if use_count >= max_uses:
                logger.warning("Token exceeded max uses: %s/%s", use_count, max_uses)
                self.revoke_token(token)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token exceeded maximum uses",
                )

            if increment_use:
                token_data["use_count"] = use_count + 1
                token_data["last_used_at"] = datetime.now(UTC).isoformat()
                self.redis.setex(
                    token_key,
                    self.token_ttl,
                    json.dumps(token_data, ensure_ascii=False),
                )

            logger.info(
                "Token verified for user %s, uses: %s",
                token_data.get("user_id"),
                token_data.get("use_count", 0),
            )
            return token_data

        except json.JSONDecodeError:
            logger.exception("Invalid token data format: %s...", token[:8])
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token format")
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Token verification error: %s", str(e))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Token verification failed",
            )

    def revoke_token(self, token: str):
        """
        Отзывает токен (удаляет из Redis)
        """
        token_key = f"{self.token_prefix}{token}"
        try:
            token_data_json = self.redis.get(token_key)
            if token_data_json:
                token_data = json.loads(token_data_json)
                order_id = token_data.get("order_id")

                if order_id:
                    order_tokens_key = f"order_tokens:{order_id}"
                    self.redis.srem(order_tokens_key, token)

            self.redis.delete(token_key)
            logger.info("Token revoked: %s...", token[:8])

        except Exception as e:
            logger.exception("Failed to revoke token: %s", str(e))

    def revoke_all_order_tokens(self, order_id: str):
        """
        Отзывает все токены для указанного заказа
        """
        order_tokens_key = f"order_tokens:{order_id}"
        try:
            tokens = self.redis.smembers(order_tokens_key)
            for token in tokens:
                token_str = token.decode() if isinstance(token, bytes) else token
                self.revoke_token(token_str)

            logger.info("Revoked all tokens for order: %s", order_id)

        except Exception as e:
            logger.exception("Failed to revoke order tokens: %s", str(e))

    def get_token_stats(self, token: str) -> dict[str, Any] | None:
        """
        Получает статистику по токену (без инкрементации счетчика)
        """
        try:
            return self.verify_ws_token(token, increment_use=False)
        except HTTPException:
            return None

    def cleanup_expired_tokens(self):
        """
        Очистка просроченных токенов (может быть запущена по cron)
        """
        try:
            token_keys = self.redis.keys(f"{self.token_prefix}*")
            deleted_count = 0

            for key in token_keys:
                key_str = key.decode() if isinstance(key, bytes) else key
                ttl = self.redis.ttl(key_str)
                if ttl < 0:
                    token_data_json = self.redis.get(key_str)
                    if token_data_json:
                        token_data = json.loads(token_data_json)
                        expires_at = datetime.fromisoformat(token_data.get("expires_at", "1970-01-01"))
                        if datetime.now(UTC) > expires_at:
                            self.redis.delete(key_str)
                            deleted_count += 1

            logger.info("Cleaned up %s expired tokens", deleted_count)
            return deleted_count

        except Exception as e:
            logger.exception("Failed to cleanup expired tokens: %s", e)
            return 0


def get_ws_token_manager() -> WebSocketTokenManager:
    """
    Возвращает инстанс менеджера токенов через DI контейнер
    """
    from api.dependencies import get_redis

    redis = get_redis()
    return WebSocketTokenManager(redis, token_ttl=600)
