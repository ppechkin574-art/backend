# import json
# import logging
# from datetime import datetime, timedelta
# from functools import wraps
# from typing import Protocol
# from uuid import UUID

# import redis.exceptions
# from pydantic import BaseModel
# from redis import Redis

# from auth.dtos import AuthRegisterDTO
# from auth.exceptions import TemporaryRegistrationNotFoundError

# logger = logging.getLogger(__name__)


# class TemporaryRegistrationDTO(BaseModel):
#     registration_id: UUID
#     user_data: AuthRegisterDTO
#     created_at: datetime
#     expires_at: datetime


# class TemporaryRegistrationRepositoryInterface(Protocol):
#     def create(self, registration_id: UUID, user_data: AuthRegisterDTO, ttl_seconds: int) -> None:
#         """Сохраняет временные данные регистрации"""
#         raise NotImplementedError

#     def get(self, registration_id: UUID) -> TemporaryRegistrationDTO:
#         """Получает временные данные регистрации"""
#         raise NotImplementedError

#     def delete(self, registration_id: UUID) -> None:
#         """Удаляет временные данные регистрации"""
#         raise NotImplementedError


# class TemporaryRegistrationRepositoryRedis:
#     def __init__(self, redis: Redis):
#         self._redis = redis

#     @staticmethod
#     def _handle_redis_errors(func):
#         @wraps(func)
#         def wrapper(self, *args, **kwargs):
#             try:
#                 return func(self, *args, **kwargs)
#             except TemporaryRegistrationNotFoundError:
#                 raise
#             except redis.exceptions.ConnectionError as e:
#                 logger.exception("Redis connection error: %s", str(e))
#                 raise
#             except redis.exceptions.RedisError as e:
#                 logger.exception("Redis error: %s", str(e))
#                 raise
#             except Exception as e:
#                 logger.exception("Unexpected redis repository error: %s", str(e))
#                 raise

#         return wrapper

#     @_handle_redis_errors
#     def create(self, registration_id: UUID, user_data: AuthRegisterDTO, ttl_seconds: int) -> None:
#         key = f"registration:{registration_id}"

#         temporary_data = {
#             "registration_id": str(registration_id),
#             "user_data": user_data.model_dump(),
#             "created_at": datetime.utcnow().isoformat(),
#             "expires_at": (datetime.utcnow() + timedelta(seconds=ttl_seconds)).isoformat(),
#         }

#         self._redis.setex(key, ttl_seconds, json.dumps(temporary_data))
#         logger.debug("Temporary registration data stored: %s", registration_id)

#     @_handle_redis_errors
#     def get(self, registration_id: UUID) -> TemporaryRegistrationDTO:
#         key = f"registration:{registration_id}"
#         data = self._redis.get(key)

#         if not data:
#             raise TemporaryRegistrationNotFoundError(f"Temporary registration not found: {registration_id}")

#         data_dict = json.loads(data)
#         data_dict["user_data"] = AuthRegisterDTO(**data_dict["user_data"])
#         data_dict["created_at"] = datetime.fromisoformat(data_dict["created_at"])
#         data_dict["expires_at"] = datetime.fromisoformat(data_dict["expires_at"])

#         return TemporaryRegistrationDTO(**data_dict)

#     @_handle_redis_errors
#     def delete(self, registration_id: UUID) -> None:
#         key = f"registration:{registration_id}"
#         if not self._redis.delete(key):
#             raise TemporaryRegistrationNotFoundError(f"Temporary registration not found: {registration_id}")
#         logger.debug("Temporary registration data deleted: %s", registration_id)
