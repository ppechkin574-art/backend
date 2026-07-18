"""RBAC regression coverage for the `marketing` Keycloak role on the admin
surface (see api/dependencies.py, commit 2499f0c "feat(rbac): marketing
sees the full admin panel, writes gated by a permission modal").

Written during a QA pass on the marketing admin account (CRM task
"Тестировка" / 2026-07-18). Pins the exact contract each of the four
role-aware dependency functions is supposed to enforce, independent of
any specific route, so a future change to one of them fails a test
instead of silently drifting from what the frontend gate
(admin/src/services/marketingWriteGate.ts) assumes.

Each dependency is called directly (bypassing FastAPI's Depends()
plumbing) with a fake AuthServiceInterface — this is cheaper and more
precise than spinning up a TestClient per case, and mirrors how
allow_only_admins etc. are simple functions of (roles, http method).
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.dependencies import (
    allow_admin_or_marketing,
    allow_crm_access,
    allow_read_or_admin_write,
    allow_settings_read_or_admin_write,
)
from auth.dtos.users import UserDTO
from auth.exceptions import AuthAccessInvalidTokenError


def _user(roles: list[str]) -> UserDTO:
    return UserDTO.model_construct(
        id=uuid4(),
        username="u",
        name="u",
        phone=None,
        email=None,
        avatar=None,
        is_active=True,
        plan="FREE",
        used_trial=False,
        subscription_end=None,
        subscription_cancelled=False,
        created_at=None,
        updated_at=None,
        attendance_streak_days=0,
        attendance_total_points=0,
        attendance_today_points=None,
        roles=roles,
    )


class _FakeAuthService:
    """Stands in for AuthServiceInterface. `get_user_from_token` returns
    whatever roles the test wired up, or raises like the real service
    does for a bad/missing token."""

    def __init__(self, roles: list[str] | None):
        self._roles = roles

    def get_user_from_token(self, token: str) -> UserDTO:
        if self._roles is None:
            raise AuthAccessInvalidTokenError
        return _user(self._roles)


def _request(method: str) -> SimpleNamespace:
    # The `request`-taking dependencies only ever read `.method`.
    return SimpleNamespace(method=method)


# ---------------------------------------------------------------------------
# allow_admin_or_marketing — analytics dashboard + push broadcast router.
# No method restriction: any role in {admin, manager, marketing} gets full
# access, because for this specific surface marketing is *meant* to write
# (send push). See notifications_send.py.
# ---------------------------------------------------------------------------
class TestAllowAdminOrMarketing:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("roles", [["admin"], ["manager"], ["marketing"], ["admin", "marketing"]])
    async def test_allowed_roles_pass(self, roles):
        user = await allow_admin_or_marketing(
            access_token="t", auth_service=_FakeAuthService(roles)
        )
        assert user.roles == roles

    @pytest.mark.asyncio
    async def test_plain_user_role_rejected(self):
        with pytest.raises(HTTPException) as exc:
            await allow_admin_or_marketing(access_token="t", auth_service=_FakeAuthService(["user"]))
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_no_roles_rejected(self):
        with pytest.raises(HTTPException) as exc:
            await allow_admin_or_marketing(access_token="t", auth_service=_FakeAuthService([]))
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_invalid_token_is_401(self):
        with pytest.raises(HTTPException) as exc:
            await allow_admin_or_marketing(access_token="t", auth_service=_FakeAuthService(None))
        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# allow_read_or_admin_write — the router used by nearly every content-
# management admin page. GET is open to marketing (read-only); every other
# method stays admin/manager-only.
# ---------------------------------------------------------------------------
class TestAllowReadOrAdminWrite:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "DELETE", "PUT"])
    @pytest.mark.parametrize("roles", [["admin"], ["manager"]])
    async def test_admin_and_manager_write_every_method(self, roles, method):
        user = await allow_read_or_admin_write(
            request=_request(method), access_token="t", auth_service=_FakeAuthService(roles)
        )
        assert user.roles == roles

    @pytest.mark.asyncio
    async def test_marketing_can_read(self):
        user = await allow_read_or_admin_write(
            request=_request("GET"), access_token="t", auth_service=_FakeAuthService(["marketing"])
        )
        assert user.roles == ["marketing"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE", "PUT"])
    async def test_marketing_cannot_write(self, method):
        with pytest.raises(HTTPException) as exc:
            await allow_read_or_admin_write(
                request=_request(method), access_token="t", auth_service=_FakeAuthService(["marketing"])
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_plain_user_cannot_even_read(self):
        with pytest.raises(HTTPException) as exc:
            await allow_read_or_admin_write(
                request=_request("GET"), access_token="t", auth_service=_FakeAuthService(["user"])
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_invalid_token_is_401(self):
        with pytest.raises(HTTPException) as exc:
            await allow_read_or_admin_write(
                request=_request("GET"), access_token="t", auth_service=_FakeAuthService(None)
            )
        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# allow_crm_access — marketing gets full read/write EXCEPT delete.
# This is the contract admin/src/services/marketingWriteGate.ts's
# isCrmTaskWrite() must mirror on the frontend.
# ---------------------------------------------------------------------------
class TestAllowCrmAccess:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "PUT"])
    async def test_marketing_can_read_and_write_except_delete(self, method):
        user = await allow_crm_access(
            request=_request(method), access_token="t", auth_service=_FakeAuthService(["marketing"])
        )
        assert user.roles == ["marketing"]

    @pytest.mark.asyncio
    async def test_marketing_cannot_delete(self):
        with pytest.raises(HTTPException) as exc:
            await allow_crm_access(
                request=_request("DELETE"), access_token="t", auth_service=_FakeAuthService(["marketing"])
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    @pytest.mark.parametrize("roles", [["admin"], ["manager"]])
    async def test_admin_and_manager_can_delete(self, roles):
        user = await allow_crm_access(
            request=_request("DELETE"), access_token="t", auth_service=_FakeAuthService(roles)
        )
        assert user.roles == roles

    @pytest.mark.asyncio
    async def test_plain_user_rejected(self):
        with pytest.raises(HTTPException) as exc:
            await allow_crm_access(
                request=_request("GET"), access_token="t", auth_service=_FakeAuthService(["user"])
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_invalid_token_is_401(self):
        with pytest.raises(HTTPException) as exc:
            await allow_crm_access(
                request=_request("GET"), access_token="t", auth_service=_FakeAuthService(None)
            )
        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# allow_settings_read_or_admin_write — app-settings: strictly admin-only
# for writes (NOT manager, unlike every other write gate — see the
# docstring in dependencies.py). marketing may read (GET) only, because
# the Рефералы policy page reads app_settings through this router.
# ---------------------------------------------------------------------------
class TestAllowSettingsReadOrAdminWrite:
    @pytest.mark.asyncio
    async def test_admin_can_write(self):
        user = await allow_settings_read_or_admin_write(
            request=_request("PUT"), access_token="t", auth_service=_FakeAuthService(["admin"])
        )
        assert user.roles == ["admin"]

    @pytest.mark.asyncio
    async def test_manager_cannot_write(self):
        # Deliberately stricter than allow_read_or_admin_write: app-settings
        # writes are admin-only, managers are excluded on purpose.
        with pytest.raises(HTTPException) as exc:
            await allow_settings_read_or_admin_write(
                request=_request("PUT"), access_token="t", auth_service=_FakeAuthService(["manager"])
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_marketing_can_read(self):
        user = await allow_settings_read_or_admin_write(
            request=_request("GET"), access_token="t", auth_service=_FakeAuthService(["marketing"])
        )
        assert user.roles == ["marketing"]

    @pytest.mark.asyncio
    async def test_marketing_cannot_write(self):
        with pytest.raises(HTTPException) as exc:
            await allow_settings_read_or_admin_write(
                request=_request("PUT"), access_token="t", auth_service=_FakeAuthService(["marketing"])
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_manager_cannot_even_read(self):
        # manager has no special case in this dependency at all — only
        # is_admin (write) or marketing-GET (read) pass.
        with pytest.raises(HTTPException) as exc:
            await allow_settings_read_or_admin_write(
                request=_request("GET"), access_token="t", auth_service=_FakeAuthService(["manager"])
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_invalid_token_is_401(self):
        with pytest.raises(HTTPException) as exc:
            await allow_settings_read_or_admin_write(
                request=_request("GET"), access_token="t", auth_service=_FakeAuthService(None)
            )
        assert exc.value.status_code == 401
