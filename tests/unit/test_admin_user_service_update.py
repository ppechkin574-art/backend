"""Unit tests for AdminUserService.update_user.

Regression guard for two bugs fixed 2026-06-10:

Bug 1 — ValidationError on block/unblock:
  update_user passed attributes=None to KeycloakUserUpdateDTO, but the field
  was declared as required (not Optional). Pydantic 2 raised ValidationError
  before Keycloak was even contacted → PATCH /admin/users/{id} returned 500
  for every is_active-only or password-only update.
  Fix: KeycloakUserUpdateDTO.attributes: ... | None = None.

Bug 2 — Admin-created users received FREE plan instead of PRO 365 days:
  AdminUserService.create_user set plan=PlanType.FREE. Fixed to PRO + 365 days.

Uses lightweight fakes — no DB, no Keycloak network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from auth.admin_service import AdminUserService
from auth.dtos.admin import AdminUserUpdateDTO, AdminUserCreateDTO
from clients.identity_provider.dtos import (
    KeycloakAttributesDTO,
    KeycloakUserDTO,
    KeycloakUserUpdateDTO,
)
from common.enums import PlanType

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

USER_ID: UUID = uuid4()


def _keycloak_user(user_id: UUID = USER_ID) -> KeycloakUserDTO:
    return KeycloakUserDTO(
        id=user_id,
        username="test_abc123",
        email="phone.77001234567@aima.internal",
        emailVerified=True,
        enabled=True,
        createdTimestamp=datetime.now(UTC),
        attributes=KeycloakAttributesDTO(
            name=["Test User"],
            plan=[PlanType.FREE.value],
            subscription_end=[],
            subscription_cancelled=[],
            used_trial=["false"],
        ),
    )


class _FakeIdentityProvider:
    """Lightweight fake — records calls for assertion, never hits network."""

    def __init__(self, user: KeycloakUserDTO | None = None) -> None:
        self._user = user or _keycloak_user()
        self.set_active_calls: list[tuple[UUID, bool]] = []
        self.set_password_calls: list[tuple[UUID, str]] = []
        self.update_user_calls: list[tuple[UUID, KeycloakUserUpdateDTO]] = []
        self.add_realm_role_calls: list[tuple[UUID, str]] = []
        self.get_or_create_calls: list[Any] = []

    def get(self, query: Any) -> KeycloakUserDTO:
        return self._user

    def get_roles(self, user_id: UUID) -> list[str]:
        return []

    def set_active(self, user_id: UUID, active: bool) -> None:
        self.set_active_calls.append((user_id, active))

    def set_password(self, user_id: UUID, password: str) -> None:
        self.set_password_calls.append((user_id, password))

    def update_user(self, user_id: UUID, dto: KeycloakUserUpdateDTO) -> None:
        self.update_user_calls.append((user_id, dto))

    def get_users(self) -> list[KeycloakUserDTO]:
        return [self._user]

    def get_or_create(self, dto: Any) -> tuple[KeycloakUserDTO, bool]:
        self.get_or_create_calls.append(dto)
        return self._user, True

    def add_realm_role(self, user_id: UUID, role: str) -> None:
        self.add_realm_role_calls.append((user_id, role))

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(
            f"AdminUserService must not call identity_provider.{name}() in this test"
        )


def _make_service() -> tuple[AdminUserService, _FakeIdentityProvider]:
    fake = _FakeIdentityProvider()
    return AdminUserService(identity_provider=fake, session=None), fake


# ---------------------------------------------------------------------------
# DTO level: KeycloakUserUpdateDTO.attributes must be Optional
# ---------------------------------------------------------------------------

class TestKeycloakUserUpdateDTOOptionalAttributes:
    """
    Bug 1 regression guard at the DTO level.
    Before the fix: KeycloakUserUpdateDTO(attributes=None) raised ValidationError.
    """

    def test_accepts_none_attributes(self):
        dto = KeycloakUserUpdateDTO(email=None, attributes=None)
        assert dto.attributes is None

    def test_default_value_is_none(self):
        dto = KeycloakUserUpdateDTO()
        assert dto.attributes is None

    def test_accepts_none_alongside_email(self):
        dto = KeycloakUserUpdateDTO(
            email="test@example.com",
            attributes=None,
        )
        assert dto.email == "test@example.com"
        assert dto.attributes is None

    def test_accepts_real_attributes_object(self):
        from clients.identity_provider.dtos import KeycloakAttributesUpdateDTO

        attrs = KeycloakAttributesUpdateDTO(name=["Alice"])
        dto = KeycloakUserUpdateDTO(attributes=attrs)
        assert dto.attributes is not None
        assert dto.attributes.name == ["Alice"]


# ---------------------------------------------------------------------------
# is_active only — exact regression scenario
# ---------------------------------------------------------------------------

class TestUpdateUserIsActiveOnly:
    """
    Regression: PATCH /admin/users/{id} with {is_active: false} must not raise.
    Previously the service crashed with Pydantic ValidationError before
    contacting Keycloak, returning HTTP 500 for every block/unblock action.
    """

    def test_block_does_not_raise(self):
        svc, _ = _make_service()
        svc.update_user(USER_ID, AdminUserUpdateDTO(is_active=False))

    def test_unblock_does_not_raise(self):
        svc, _ = _make_service()
        svc.update_user(USER_ID, AdminUserUpdateDTO(is_active=True))

    def test_block_returns_user_dto(self):
        svc, _ = _make_service()
        result = svc.update_user(USER_ID, AdminUserUpdateDTO(is_active=False))
        assert result is not None
        assert result.id == USER_ID

    def test_block_calls_set_active_with_false(self):
        svc, fake = _make_service()
        svc.update_user(USER_ID, AdminUserUpdateDTO(is_active=False))
        assert fake.set_active_calls == [(USER_ID, False)]

    def test_unblock_calls_set_active_with_true(self):
        svc, fake = _make_service()
        svc.update_user(USER_ID, AdminUserUpdateDTO(is_active=True))
        assert fake.set_active_calls == [(USER_ID, True)]

    def test_block_does_not_call_set_password(self):
        svc, fake = _make_service()
        svc.update_user(USER_ID, AdminUserUpdateDTO(is_active=False))
        assert fake.set_password_calls == []

    def test_keycloak_update_dto_has_no_attributes_when_only_is_active(self):
        """
        When only is_active is provided, no profile fields change.
        The Keycloak update DTO must pass attributes=None (not some partial object).
        """
        svc, fake = _make_service()
        svc.update_user(USER_ID, AdminUserUpdateDTO(is_active=False))

        assert len(fake.update_user_calls) == 1
        _, dto = fake.update_user_calls[0]
        assert dto.attributes is None

    def test_is_active_none_does_not_call_set_active(self):
        """
        Not passing is_active (= None default) means «don't touch» —
        set_active must never be called.
        """
        svc, fake = _make_service()
        svc.update_user(USER_ID, AdminUserUpdateDTO(name="Alice"))
        assert fake.set_active_calls == []


# ---------------------------------------------------------------------------
# password only
# ---------------------------------------------------------------------------

class TestUpdateUserPasswordOnly:
    """Same regression: password-only update also passed attributes=None."""

    def test_password_change_does_not_raise(self):
        svc, _ = _make_service()
        svc.update_user(USER_ID, AdminUserUpdateDTO(password="newpass1"))

    def test_password_change_calls_set_password(self):
        svc, fake = _make_service()
        svc.update_user(USER_ID, AdminUserUpdateDTO(password="newpass1"))
        assert fake.set_password_calls == [(USER_ID, "newpass1")]

    def test_password_change_does_not_call_set_active(self):
        svc, fake = _make_service()
        svc.update_user(USER_ID, AdminUserUpdateDTO(password="newpass1"))
        assert fake.set_active_calls == []

    def test_keycloak_update_dto_has_no_attributes_when_only_password(self):
        svc, fake = _make_service()
        svc.update_user(USER_ID, AdminUserUpdateDTO(password="newpass1"))
        _, dto = fake.update_user_calls[0]
        assert dto.attributes is None


# ---------------------------------------------------------------------------
# name / allowed_subject_ids — normal attribute update path
# ---------------------------------------------------------------------------

class TestUpdateUserProfileAttributes:
    def test_name_change_does_not_raise(self):
        svc, _ = _make_service()
        svc.update_user(USER_ID, AdminUserUpdateDTO(name="Алия"))

    def test_name_change_passes_attributes_to_keycloak(self):
        svc, fake = _make_service()
        svc.update_user(USER_ID, AdminUserUpdateDTO(name="Алия"))

        _, dto = fake.update_user_calls[0]
        assert dto.attributes is not None
        assert dto.attributes.name == ["Алия"]

    def test_subject_ids_serialized_as_strings(self):
        """IDs are int in our DTO but Keycloak stores them as str."""
        svc, fake = _make_service()
        svc.update_user(USER_ID, AdminUserUpdateDTO(allowed_subject_ids=[1, 2, 3]))

        _, dto = fake.update_user_calls[0]
        assert dto.attributes.allowed_subject_ids == ["1", "2", "3"]

    def test_empty_subject_ids_stored_as_empty_list(self):
        svc, fake = _make_service()
        svc.update_user(USER_ID, AdminUserUpdateDTO(allowed_subject_ids=[]))

        _, dto = fake.update_user_calls[0]
        assert dto.attributes.allowed_subject_ids == []


# ---------------------------------------------------------------------------
# Combined: is_active + name
# ---------------------------------------------------------------------------

class TestUpdateUserCombined:
    def test_is_active_and_name_does_not_raise(self):
        svc, _ = _make_service()
        svc.update_user(USER_ID, AdminUserUpdateDTO(is_active=False, name="Алия"))

    def test_is_active_and_name_calls_both_set_active_and_update_user(self):
        svc, fake = _make_service()
        svc.update_user(USER_ID, AdminUserUpdateDTO(is_active=False, name="Алия"))

        assert fake.set_active_calls == [(USER_ID, False)]
        assert len(fake.update_user_calls) == 1

        _, dto = fake.update_user_calls[0]
        assert dto.attributes is not None
        assert dto.attributes.name == ["Алия"]
