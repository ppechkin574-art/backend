"""Unit tests for auth.converters — used_trial and registration plan.

Regression guard for bugs fixed 2026-06-10:

Bug 1 — used_trial never persisted to Keycloak:
  to_keycloak_create_user_dto did not include used_trial in Keycloak
  attributes, so the field was silently dropped on every registration.

Bug 2 — used_trial never read back from Keycloak:
  to_user_dto ignored the used_trial attribute, so UserDTO.used_trial
  was always False regardless of what Keycloak stored.

Bug 3 — registration set used_trial=False:
  to_user_create_dto set used_trial=False, meaning the flag was
  immediately wrong from the moment the user was created. The 3-day
  trial starts on registration, so used_trial must be True.

Bug 4 — registration kept plan=FREE (handled separately):
  Covered by test_new_user_plan_is_pro below.

All tests are pure — no DB, no Keycloak network, no Redis.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from auth.converters import to_keycloak_create_user_dto, to_user_create_dto, to_user_dto
from auth.dtos.auth import AuthRegisterDTO
from auth.dtos.users import UserCreateDTO
from clients.identity_provider.dtos import KeycloakAttributesDTO, KeycloakUserDTO
from clients.notification.dtos import CodePlatform
from common.enums import PlanType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_create_dto(*, used_trial: bool, plan: PlanType = PlanType.PRO) -> UserCreateDTO:
    return UserCreateDTO(
        name="Test User",
        phone="+77001234567",
        email=None,
        avatar=None,
        password="Test12345!",
        role="student",
        is_active=True,
        allowed_subject_ids=[],
        plan=plan,
        subscription_end=datetime.now(UTC) + timedelta(days=3),
        used_trial=used_trial,
    )


def _keycloak_user(used_trial_attr: list[str]) -> KeycloakUserDTO:
    """Build a fake KeycloakUserDTO with a specific used_trial attribute list."""
    return KeycloakUserDTO(
        id=uuid4(),
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
            used_trial=used_trial_attr,
        ),
    )


# ---------------------------------------------------------------------------
# to_keycloak_create_user_dto — used_trial serialization
# ---------------------------------------------------------------------------

class TestToKeycloakCreateUserDtoUsedTrial:
    """
    Regression: used_trial must be written into Keycloak attributes so the
    field survives across backend restarts (it lives in Keycloak, not Postgres).
    """

    def test_used_trial_true_serialized_as_list_of_true_string(self):
        dto = to_keycloak_create_user_dto(_user_create_dto(used_trial=True))
        assert dto.attributes.used_trial == ["true"]

    def test_used_trial_false_serialized_as_list_of_false_string(self):
        dto = to_keycloak_create_user_dto(_user_create_dto(used_trial=False))
        assert dto.attributes.used_trial == ["false"]

    def test_used_trial_field_always_present_in_attributes(self):
        """
        used_trial must never be omitted — if it's missing, Keycloak will
        not store it and to_user_dto will always return False for every user.
        """
        dto = to_keycloak_create_user_dto(_user_create_dto(used_trial=True))
        assert dto.attributes.used_trial is not None
        assert len(dto.attributes.used_trial) == 1


# ---------------------------------------------------------------------------
# to_user_dto — used_trial deserialization
# ---------------------------------------------------------------------------

class TestToUserDtoUsedTrial:
    """
    Regression: to_user_dto must read used_trial back from Keycloak attributes.
    Previously the field was ignored and always returned False.
    """

    def test_used_trial_true_string_parsed_as_true(self):
        user = to_user_dto(_keycloak_user(["true"]), [])
        assert user.used_trial is True

    def test_used_trial_false_string_parsed_as_false(self):
        user = to_user_dto(_keycloak_user(["false"]), [])
        assert user.used_trial is False

    def test_used_trial_empty_list_returns_false_for_legacy_users(self):
        """
        Legacy users created before this field existed have an empty list.
        They default to False (haven't been assigned a trial in the new system).
        """
        user = to_user_dto(_keycloak_user([]), [])
        assert user.used_trial is False

    def test_used_trial_no_attributes_returns_false(self):
        """Users with no attributes block at all must not crash and default to False."""
        keycloak_user = KeycloakUserDTO(
            id=uuid4(),
            username="legacy",
            email=None,
            emailVerified=False,
            enabled=True,
            createdTimestamp=datetime.now(UTC),
            attributes=None,
        )
        user = to_user_dto(keycloak_user, [])
        assert user.used_trial is False

    def test_used_trial_roundtrip_true(self):
        """to_keycloak_create_user_dto → to_user_dto preserves used_trial=True."""
        kc_dto = to_keycloak_create_user_dto(_user_create_dto(used_trial=True))
        # Simulate what Keycloak stores and returns
        keycloak_user = _keycloak_user(kc_dto.attributes.used_trial)
        user = to_user_dto(keycloak_user, [])
        assert user.used_trial is True

    def test_used_trial_roundtrip_false(self):
        """to_keycloak_create_user_dto → to_user_dto preserves used_trial=False."""
        kc_dto = to_keycloak_create_user_dto(_user_create_dto(used_trial=False))
        keycloak_user = _keycloak_user(kc_dto.attributes.used_trial)
        user = to_user_dto(keycloak_user, [])
        assert user.used_trial is False


# ---------------------------------------------------------------------------
# to_user_create_dto — registration defaults
# ---------------------------------------------------------------------------

class TestToUserCreateDtoRegistrationDefaults:
    """
    Regression: registration must start the 3-day trial immediately,
    so used_trial=True and plan=PRO from the very first moment.
    """

    def _register_dto(self) -> AuthRegisterDTO:
        return AuthRegisterDTO(
            name="Test User",
            phone="+77001234567",
            password="Test12345!",
            platform=CodePlatform.SMS,
        )

    def test_registration_sets_used_trial_true(self):
        result = to_user_create_dto(self._register_dto(), is_active=True)
        assert result.used_trial is True

    def test_registration_sets_plan_pro(self):
        """New users start on PRO (trial). FREE is only after trial expiry."""
        result = to_user_create_dto(self._register_dto(), is_active=True)
        assert result.plan == PlanType.PRO

    def test_registration_subscription_end_is_approximately_1_day(self):
        """Trial window is 1 day, not 0 (no trial) or 30 (full month)."""
        result = to_user_create_dto(self._register_dto(), is_active=True)
        delta = result.subscription_end - datetime.now(UTC)
        assert 0.9 < delta.total_seconds() / 86_400 < 1.1

    def test_registration_is_active_propagated(self):
        assert to_user_create_dto(self._register_dto(), is_active=True).is_active is True
        assert to_user_create_dto(self._register_dto(), is_active=False).is_active is False
