"""CacheService.make_key — keys compiled the same way every time across
processes; otherwise different replicas would write to different Redis
keys and cache invalidation by_resource wouldn't catch them all.
"""

from unittest.mock import MagicMock
from uuid import UUID

from utils.cache import CacheService, CacheStrategy


def _service() -> CacheService:
    """Built with a stub Redis — make_key never touches the network."""
    redis_stub = MagicMock()
    return CacheService(redis_client=redis_stub, default_ttl=60)


def test_global_key_format():
    svc = _service()
    key = svc.make_key(CacheStrategy.GLOBAL, resource="subjects", params="page=1")
    assert key == "global:subjects:page=1"


def test_user_key_includes_user_id():
    svc = _service()
    user_id = UUID("547db5e0-30ec-466d-abff-70897de47c25")
    key = svc.make_key(
        CacheStrategy.USER,
        user_id=user_id,
        resource="user_points",
        params="total",
    )
    assert key == "user:547db5e0-30ec-466d-abff-70897de47c25:user_points:total"


def test_keys_with_same_inputs_are_byte_equal():
    """Stable hashing — caching across replicas/restarts depends on this."""
    svc = _service()
    key_a = svc.make_key(CacheStrategy.GLOBAL, resource="subjects", params="")
    key_b = svc.make_key(CacheStrategy.GLOBAL, resource="subjects", params="")
    assert key_a == key_b


def test_keys_differ_when_user_id_differs():
    svc = _service()
    a = svc.make_key(CacheStrategy.USER, user_id="user-A", resource="x", params="")
    b = svc.make_key(CacheStrategy.USER, user_id="user-B", resource="x", params="")
    assert a != b


def test_keys_differ_when_resource_differs():
    svc = _service()
    a = svc.make_key(CacheStrategy.GLOBAL, resource="subjects", params="")
    b = svc.make_key(CacheStrategy.GLOBAL, resource="topics", params="")
    assert a != b
