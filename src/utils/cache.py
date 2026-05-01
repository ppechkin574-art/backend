import json
import logging
from collections.abc import Callable
from enum import Enum
from functools import wraps
from typing import Any, TypeVar
from uuid import UUID

import redis
from pydantic import TypeAdapter
from redis import Redis

logger = logging.getLogger(__name__)

T = TypeVar("T")
F = TypeVar("F", bound=Callable)


class CacheStrategy(Enum):
    GLOBAL = "global"
    USER = "user"


class CacheService:
    def __init__(self, redis_client: Redis, default_ttl: int = 3600):
        self.redis = redis_client
        self.default_ttl = default_ttl

    def _serialize(self, data: Any) -> str:
        try:

            class CustomJSONEncoder(json.JSONEncoder):
                def default(self, obj):
                    if isinstance(obj, Enum):
                        return obj.value
                    elif hasattr(obj, "model_dump"):
                        return obj.model_dump()
                    elif hasattr(obj, "dict"):
                        return obj.dict()
                    return str(obj)

            return json.dumps(data, cls=CustomJSONEncoder, ensure_ascii=False)

        except Exception:
            return json.dumps(str(data), ensure_ascii=False)

    def _deserialize(self, data: str, return_type: Any = None) -> Any:
        try:
            if not data:
                return None
            result = json.loads(data)
            if return_type is not None:
                adapter = TypeAdapter(return_type)
                return adapter.validate_python(result)
            return result
        except Exception:
            return None

    def make_key(self, strategy: CacheStrategy, **kwargs) -> str:
        parts = [strategy.value]

        if strategy == CacheStrategy.GLOBAL:
            parts.extend([kwargs.get("resource"), kwargs.get("params", "")])
        elif strategy == CacheStrategy.USER:
            parts.extend(
                [
                    str(kwargs["user_id"]),
                    kwargs.get("resource"),
                    kwargs.get("params", ""),
                ]
            )

        return ":".join(str(part) for part in parts if part)

    def get(self, key: str, return_type: Any = None) -> Any:
        try:
            data = self.redis.get(key)
            if data:
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                logger.info("Cache hit: %s", key)
                return self._deserialize(data, return_type)
            logger.info("Cache miss: %s", key)
            return None
        except redis.RedisError as e:
            logger.exception("Redis error (get): %s", e)
            return None

    def set(self, key: str, data: Any, ttl: int | None = None) -> bool:
        try:
            serialized = self._serialize(data)
            ttl = ttl or self.default_ttl
            result = self.redis.setex(key, ttl, serialized)
            logger.info("Cache set: %s (ttl: %s)", key, ttl)
            return result
        except redis.RedisError as e:
            logger.exception("Redis error (set): %s", e)
            return False

    def delete(self, key: str) -> bool:
        try:
            result = self.redis.delete(key)
            logger.info("Cache delete: %s (deleted: %s)", key, result)
            return bool(result)
        except redis.RedisError as e:
            logger.exception("Redis error (delete): %s", e)
            return False

    def delete_pattern(self, pattern: str) -> int:
        try:
            keys = self.redis.keys(pattern)
            if keys:
                deleted = self.redis.delete(*keys)
                logger.info(
                    "Cache delete pattern: %s (keys: %s, deleted: %s)",
                    pattern,
                    keys,
                    deleted,
                )
                return deleted
            return 0
        except redis.RedisError as e:
            logger.exception("Redis error (delete_pattern): %s", e)
            return 0

    def flush_all(self) -> bool:
        """Очистить всю текущую базу Redis. Использовать после массового изменения данных
        (например после применения дампа БД), чтобы убрать stale-кеш с пустыми ответами."""
        try:
            self.redis.flushdb()
            logger.warning("Cache flushed entirely")
            return True
        except redis.RedisError as e:
            logger.exception("Redis error (flush_all): %s", e)
            return False

    def invalidate_by_resource(self, resource: str, user_id: UUID | None = None) -> int:
        return self.delete_pattern(f"user:user:{user_id}:{resource}:*" if user_id else f"global:{resource}:*")

    def invalidate_by_resources(self, resources: list[str], user_id: UUID | None = None) -> int:
        total_deleted = 0
        for resource in resources:
            total_deleted += self.invalidate_by_resource(resource, user_id)

        logger.info(
            "Invalidated %s resources, deleted %s keys",
            len(resources),
            total_deleted,
        )
        return total_deleted

    def get_or_set(
        self,
        key: str,
        factory: Callable[[], T],
        ttl: int | None = None,
        return_type: Any = None,
    ) -> T:
        cached = self.get(key, return_type)
        if cached is not None:
            return cached
        data = factory()
        self.set(key, data, ttl)
        return data


def cached(
    strategy: CacheStrategy,
    ttl: int = 3600,
    resource: str | None = None,
):
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            cache_service = getattr(self, "_cache_service", None)

            if not cache_service:
                return func(self, *args, **kwargs)

            key_kwargs = {"resource": resource or func.__name__}

            if strategy == CacheStrategy.USER:
                if func.__name__ == "get_subjects_with_progress":
                    import inspect

                    sig = inspect.signature(func)
                    bound_args = sig.bind(self, *args, **kwargs)
                    bound_args.apply_defaults()

                    user_id = bound_args.arguments.get("user_id")
                    only_correct = bound_args.arguments.get("only_correct", True)

                    if user_id:
                        key_kwargs["user_id"] = user_id
                        key_kwargs["params"] = f"only_correct={only_correct}"
                    else:
                        logger.warning("CACHE DEBUG: user_id not found")
                        return func(self, *args, **kwargs)

                elif func.__name__ == "get_trainers_by_subject" and len(args) >= 3:
                    subject_id = args[1]
                    student_id = args[2]

                    key_kwargs["user_id"] = student_id
                    key_kwargs["params"] = f"subject_id={subject_id}"
                elif func.__name__ == "get_ents":
                    dto = None
                    if args and len(args) > 0:
                        dto = args[0]
                    elif "option_params_dto" in kwargs:
                        dto = kwargs["option_params_dto"]

                    if dto and hasattr(dto, "student_guid") and hasattr(dto, "subject_id"):
                        user_id = dto.student_guid
                        subject_id = dto.subject_id
                        key_kwargs["user_id"] = user_id
                        key_kwargs["params"] = f"subject_id={subject_id}"
                    else:
                        return func(self, *args, **kwargs)
                elif func.__name__ in [
                    "get_attempt_detail",
                    "get_attempt_result",
                    "get_attempt_details",
                ]:
                    attempt_id = None
                    student_guid = None
                    if len(args) >= 2:
                        attempt_id = args[0]
                        student_guid = args[1]
                    else:
                        attempt_id = kwargs.get("attempt_id")
                        student_guid = kwargs.get("student_guid")

                    if student_guid and attempt_id:
                        key_kwargs["user_id"] = student_guid
                        key_kwargs["params"] = f"attempt_id={attempt_id}"
                    else:
                        logger.warning(
                            "CACHE DEBUG: Cannot extract attempt_id or student_guid for get_attempt_detail, bypassing cache"
                        )
                        return func(self, *args, **kwargs)
                elif func.__name__ == "get_last_completed_attempt_statistics":
                    trainer_id = args[1] if len(args) >= 2 else kwargs.get("trainer_id")
                    student_guid = args[2] if len(args) >= 3 else kwargs.get("student_guid")
                    if student_guid and trainer_id:
                        key_kwargs["user_id"] = student_guid
                        key_kwargs["params"] = f"trainer_id={trainer_id}"
                    else:
                        logger.warning(...)
                        return func(self, *args, **kwargs)
                else:
                    user_id = None
                    if "user_id" in kwargs:
                        user_id = kwargs["user_id"]
                    elif "student_guid" in kwargs:
                        user_id = kwargs["student_guid"]
                    elif "student_id" in kwargs:
                        user_id = kwargs["student_id"]
                    elif len(args) > 1 and isinstance(args[1], str | UUID):
                        user_id = args[1]
                    elif len(args) > 0 and hasattr(args[0], "id"):
                        user_id = args[0].id
                    elif len(args) > 0 and hasattr(args[0], "student_guid"):
                        user_id = args[0].student_guid
                    elif hasattr(self, "current_user"):
                        user_id = self.current_user.id if self.current_user else None

                    if not user_id:
                        return func(self, *args, **kwargs)

                    key_kwargs["user_id"] = user_id
                    key_kwargs["params"] = _make_cache_params(kwargs)

            elif strategy == CacheStrategy.GLOBAL:
                all_params = {}

                import inspect

                sig = inspect.signature(func)
                bound_args = sig.bind(self, *args, **kwargs)
                bound_args.apply_defaults()

                for param_name, param_value in bound_args.arguments.items():
                    if param_name not in ["self", "_cache_service", "cache_service"]:
                        all_params[param_name] = param_value

                key_kwargs["params"] = _make_cache_params(all_params)

            try:
                return_type = None
                if hasattr(func, "__annotations__") and "return" in func.__annotations__:
                    return_type = func.__annotations__["return"]

                key = cache_service.make_key(strategy, **key_kwargs)

                def factory():
                    return func(self, *args, **kwargs)

                result = cache_service.get_or_set(key, factory, ttl, return_type)
                if result is not None:
                    logger.info("CACHE DEBUG: Cache hit for %s", key)
                else:
                    logger.info("CACHE DEBUG: Cache miss and stored for %s", key)

                return result

            except Exception as e:
                logger.exception("Cache error for %s: %s", func.__name__, e)
                return func(self, *args, **kwargs)

        return wrapper

    return decorator


def _make_cache_params(params: dict) -> str:
    if not params:
        return ""
    exclude_keys = {
        "user",
        "student",
        "request",
        "self",
        "cls",
        "_cache_service",
        "cache_service",
    }
    filtered = {k: v for k, v in params.items() if k not in exclude_keys and not k.startswith("_")}
    if not filtered:
        return ""

    sorted_items = sorted(filtered.items())
    return ":".join(f"{k}={v}" for k, v in sorted_items)
