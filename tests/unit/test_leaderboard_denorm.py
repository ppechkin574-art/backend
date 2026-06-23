"""Leaderboard denormalization — `_resolve_display` / `_is_fresh`.

Proves the Postgres-snapshot path: a FRESH snapshot is served with zero Keycloak
calls; a miss or stale row falls back to the (Redis-cached) Keycloak lookup and
is persisted so the next render is pure SQL; orphans and the transient-outage
placeholder are never persisted.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

# Eager imports so SQLAlchemy mappers resolve.
from payments import models as _payment_models  # noqa: F401
from promocodes import models as _promocode_models  # noqa: F401
from subscription import models as _subscription_models  # noqa: F401

from api.routes.user.leaderboard import _is_fresh, _resolve_display
from clients.identity_provider import IdentityNotFound


def _now():
    return datetime.now(timezone.utc)


def _miss_cache():
    """Cache that always misses → _cached_display_pair hits Keycloak."""
    cache = MagicMock()
    cache.get.return_value = None
    return cache


def _idp_with(name="Иван", avatar="a.jpg"):
    idp = MagicMock()
    user = MagicMock()
    user.attributes.name = [name]
    user.attributes.avatar = [avatar] if avatar else None
    idp.get_user.return_value = user
    return idp


# ─────────────────────────── _is_fresh ───────────────────────────


def test_is_fresh_recent_is_true():
    assert _is_fresh(_now() - timedelta(minutes=5)) is True


def test_is_fresh_old_is_false():
    assert _is_fresh(_now() - timedelta(hours=12)) is False


def test_is_fresh_none_is_false():
    assert _is_fresh(None) is False


def test_is_fresh_naive_datetime_treated_as_utc():
    naive = _now().replace(tzinfo=None) - timedelta(minutes=1)
    assert _is_fresh(naive) is True


# ─────────────────────────── _resolve_display ────────────────────


def test_fresh_snapshot_skips_keycloak():
    idp = _idp_with("Кэш", "c.jpg")
    repo = MagicMock()
    snapshots = {"u1": ("Снимок", "snap.jpg", _now() - timedelta(minutes=10))}

    pair, wrote = _resolve_display("u1", snapshots, idp, _miss_cache(), repo)

    assert pair == ("Снимок", "snap.jpg")
    assert wrote is False
    idp.get_user.assert_not_called()  # pure SQL — no Keycloak
    repo.upsert.assert_not_called()


def test_missing_snapshot_falls_back_to_keycloak_and_persists():
    idp = _idp_with("Иван", "a.jpg")
    repo = MagicMock()

    pair, wrote = _resolve_display("u2", {}, idp, _miss_cache(), repo)

    assert pair == ("Иван", "a.jpg")
    assert wrote is True
    idp.get_user.assert_called_once()
    repo.upsert.assert_called_once_with("u2", "Иван", "a.jpg")


def test_stale_snapshot_revalidates_and_persists():
    idp = _idp_with("Новое", "new.jpg")
    repo = MagicMock()
    snapshots = {"u3": ("Старое", "old.jpg", _now() - timedelta(hours=12))}

    pair, wrote = _resolve_display("u3", snapshots, idp, _miss_cache(), repo)

    assert pair == ("Новое", "new.jpg")
    assert wrote is True
    idp.get_user.assert_called_once()
    repo.upsert.assert_called_once()


def test_orphan_is_not_persisted():
    idp = MagicMock()
    idp.get_user.side_effect = IdentityNotFound
    repo = MagicMock()

    pair, wrote = _resolve_display("gone", {}, idp, _miss_cache(), repo)

    assert pair is None
    assert wrote is False
    repo.upsert.assert_not_called()


def test_transient_placeholder_is_not_persisted():
    idp = MagicMock()
    idp.get_user.side_effect = Exception("Keycloak 5xx")
    repo = MagicMock()

    pair, wrote = _resolve_display("flaky", {}, idp, _miss_cache(), repo)

    assert pair == ("Пользователь", None)
    assert wrote is False
    repo.upsert.assert_not_called()
