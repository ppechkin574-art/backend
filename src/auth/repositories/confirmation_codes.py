import logging
from enum import Enum
from functools import wraps
from typing import Protocol
from uuid import UUID

import redis.exceptions
from redis import Redis

from auth.converters import to_redis_confirmation_code
from auth.dtos import (
    ConfirmationCodeCreateDTO,
    ConfirmationCodeDTO,
    ConfirmationCodeQueryDTO,
)
from auth.dtos.confirmation_codes import ConfirmationCodeAction
from auth.exceptions import ConfirmationCodeExistsError, ConfirmationCodeNotFoundError

logger = logging.getLogger(__name__)


class ConfirmationCodeRepositoryInterface(Protocol):
    def create(self, user: ConfirmationCodeCreateDTO) -> UUID:
        """
        Create temporary user for `expiration` amount of time.

        Args:
            user: Temporary User Create DTO.

        Raises:
            ConfirmationCodeExistsError: Entry with such `user_id` already exists.
        """
        raise NotImplementedError

    def get(self, user: ConfirmationCodeQueryDTO) -> ConfirmationCodeDTO:
        """
        Get temporary user.

        Args:
            user: Temporary User Query DTO.

        Returns:
            ConfirmationCodeDTO: Temporary user information.

        Raises:
            ConfirmationCodeNotFoundError: Entry with such `id` not found.
        """
        raise NotImplementedError

    def delete(self, confirmation_code_id: UUID) -> None:
        """
        Delete temporary user.

        Args:
            confirmation_code_id: ID of the temporary user to delete.

        Raises:
            ConfirmationCodeNotFoundError: Entry with such `id` not found.
        """
        raise NotImplementedError


class ConfirmationCodeRepositoryRedis:
    def __init__(self, redis: Redis):
        self._redis = redis

    @staticmethod
    def _handle_redis_errors(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except ConfirmationCodeNotFoundError:
                raise
            except ConfirmationCodeExistsError:
                raise
            except redis.exceptions.ConnectionError as e:
                logger.exception("Redis connection error: %s", str(e))
                return None
            except redis.exceptions.RedisError as e:
                logger.exception("Redis error: %s", str(e))
                return None
            except Exception as e:
                logger.exception("Unexpected redis repository error: %s", str(e))
                return None

        return wrapper

    @staticmethod
    def _serialize_for_redis(data_dict: dict) -> dict:
        """Конвертирует все значения в строки для Redis"""
        serialized = {}
        for key, value in data_dict.items():
            if value is None:
                continue
            if isinstance(value, bool):
                serialized[key] = "true" if value else "false"
            elif isinstance(value, int | float | UUID):
                serialized[key] = str(value)
            elif isinstance(value, Enum):
                serialized[key] = value.value
            else:
                serialized[key] = str(value)
        return serialized

    @staticmethod
    def decode_redis_hash(data: dict) -> dict:
        return {k.decode(): v.decode() for k, v in data.items()}

    @staticmethod
    def decode_redis_set(data: set[bytes]) -> set[str]:
        return {item.decode() for item in data}

    def _find_confirmation_code_by_action(
        self,
        identifier: UUID,
        action: str,
        is_temporary: bool = False,
    ) -> dict | None:
        index_type = "temp_reg" if is_temporary else "user"
        index_key = f"index:{index_type}_id:{identifier}"
        keys = self.decode_redis_set(self._redis.smembers(index_key))

        for key in keys:
            confirmation_code = self.decode_redis_hash(self._redis.hgetall(key))
            if confirmation_code.get("action") == action and confirmation_code.get("is_temporary", "false") == (
                "true" if is_temporary else "false"
            ):
                return confirmation_code
        return None

    @_handle_redis_errors
    def create(self, code_data: ConfirmationCodeCreateDTO) -> UUID:
        identifier = code_data.registration_id if code_data.is_temporary else code_data.user_id

        if identifier is None:
            raise ValueError("Identifier cannot be None for confirmation code")

        existing_code = self._find_confirmation_code_by_action(
            identifier, code_data.action.value, code_data.is_temporary
        )
        if existing_code:
            logger.warning("Confirmation code already exists: %s", existing_code)
            raise ConfirmationCodeExistsError(
                confirmation_code_id=UUID(existing_code.get("id")),
                message=f"Confirmation code for action {code_data.action} already exists",
            )

        redis_confirmation_code = to_redis_confirmation_code(code_data)
        key = str(redis_confirmation_code.id)

        redis_dict = self._serialize_for_redis(redis_confirmation_code.model_dump())

        redis_dict["verified"] = "false"

        if code_data.user_id:
            redis_dict["real_user_id"] = str(code_data.user_id)

        logger.info(
            "Saving to Redis - Key: %s, Data: %s, TTL: %s",
            key,
            redis_dict,
            code_data.expiration,
        )

        logger.debug("Saving confirmation code to Redis: %s", redis_dict)
        self._redis.hset(key, mapping=redis_dict)
        logger.info("Redis HSET result: %s", redis_dict)
        self._redis.expire(key, code_data.expiration)

        index_type = "temp_reg" if code_data.is_temporary else "user"
        index_key = f"index:{index_type}_id:{identifier}"
        logger.info("Adding to index: %s", index_key)
        index_result = self._redis.sadd(index_key, key)
        logger.info("Redis SADD result: %s", index_result)

        return redis_confirmation_code.id

    @_handle_redis_errors
    def get(self, query: ConfirmationCodeQueryDTO) -> ConfirmationCodeDTO:
        identifier = query.registration_id if query.is_temporary else query.user_id

        if identifier is None:
            raise ConfirmationCodeNotFoundError("Identifier cannot be None")

        logger.info(
            "Looking for confirmation code - Identifier: %s, Action: %s, Temporary: %s, Code: %s",
            identifier,
            query.action,
            query.is_temporary,
            query.code,
        )

        index_type = "temp_reg" if query.is_temporary else "user"
        index_key = f"index:{index_type}_id:{identifier}"
        logger.info("Searching in index: %s", index_key)

        keys = self.decode_redis_set(self._redis.smembers(index_key))
        logger.info("Found keys in index: %s", keys)

        confirmation_code_data = self._find_confirmation_code_by_action(
            identifier, query.action.value if query.action else "", query.is_temporary
        )

        if not confirmation_code_data:
            raise ConfirmationCodeNotFoundError(f"Confirmation code not found for identifier: {identifier}")

        logger.info("Found confirmation code: %s", confirmation_code_data)

        try:
            confirmation_code_id = UUID(confirmation_code_data["id"])
            user_id_str = confirmation_code_data.get("real_user_id") or confirmation_code_data.get("user_id")
            registration_id_str = confirmation_code_data.get("registration_id")
            code = int(confirmation_code_data["code"])
            action = ConfirmationCodeAction(confirmation_code_data["action"])
            incorrect_count = int(confirmation_code_data.get("incorrect_count", "0"))
            contact = confirmation_code_data.get("contact")

            created_at_str = confirmation_code_data.get("created_at")
            expires_at_str = confirmation_code_data.get("expires_at")

            created_at = None
            expires_at = None
            if created_at_str:
                created_at = created_at_str
            if expires_at_str:
                expires_at = expires_at_str

            correct = False

            if query.code is not None:
                correct = code == query.code

                if not correct:
                    new_incorrect_count = incorrect_count + 1
                    self._redis.hset(
                        confirmation_code_data["id"],
                        "incorrect_count",
                        str(new_incorrect_count),
                    )
                    incorrect_count = new_incorrect_count
                else:
                    self._redis.hset(
                        confirmation_code_data["id"],
                        "verified",
                        "true",
                    )
            else:
                verified_str = confirmation_code_data.get("verified", "false")
                correct = verified_str == "true"

            user_id = UUID(user_id_str) if user_id_str else None
            registration_id = UUID(registration_id_str) if registration_id_str else None

            confirmation_code_dto = ConfirmationCodeDTO(
                id=confirmation_code_id,
                user_id=user_id,
                registration_id=registration_id,
                contact=contact,
                code=code,
                correct=correct,
                action=action,
                incorrect_count=incorrect_count,
                created_at=created_at,
                expires_at=expires_at,
            )

            return confirmation_code_dto

        except (KeyError, ValueError) as e:
            logger.exception(
                "Invalid confirmation code data: %s, data: %s",
                e,
                confirmation_code_data,
            )
            raise ConfirmationCodeNotFoundError("Invalid confirmation code data")

    @_handle_redis_errors
    def delete(self, confirmation_code_id: UUID) -> None:
        key = str(confirmation_code_id)

        if not self._redis.exists(key):
            raise ConfirmationCodeNotFoundError(f"Confirmation code not found: {key}")

        data = self.decode_redis_hash(self._redis.hgetall(key))
        is_temporary = data.get("is_temporary", "false") == "true"
        identifier = data.get("user_id")

        if identifier:
            index_type = "temp_reg" if is_temporary else "user"
            index_key = f"index:{index_type}_id:{identifier}"
            self._redis.srem(index_key, key)

        self._redis.delete(key)
