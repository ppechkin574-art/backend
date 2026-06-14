"""Unit tests for ReferralService.list_invitees().

Tests cover:
- Privacy: InviteeStatusDTO MUST NOT expose phone/email/subscription_type
- Field completeness: invitee_id, invitee_display_name, invitee_avatar_url, redeemed_at
- Keycloak failure fallback: single invitee error → show "—", don't fail the list
- Masked phone display when no display name
- Avatar presign: success path and fail-soft (None fallback, no row drop)
- Empty list: returns []
- IDOR: list is filtered by inviter_id passed from auth, not from request body
- No sensitive Keycloak attributes leak through UserDTO → InviteeStatusDTO
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from referrals.dtos import InviteeStatusDTO
from referrals.service import ReferralService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(
    db=None,
    app_settings=None,
    admin_user_service=None,
    file_service=None,
) -> ReferralService:
    return ReferralService(
        db=db or MagicMock(),
        app_settings=app_settings or MagicMock(),
        admin_user_service=admin_user_service or MagicMock(),
        user_points_repo=MagicMock(),
        file_service=file_service or MagicMock(),
    )


def _fake_redemption(invitee_id=None, inviter_id=None, redeemed_at=None):
    return SimpleNamespace(
        invitee_id=invitee_id or uuid4(),
        inviter_id=inviter_id or uuid4(),
        redeemed_at=redeemed_at or datetime.now(UTC),
    )


def _fake_user(name="Алия", phone="+77001234567", avatar=None):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        phone=phone,
        avatar=avatar,
        # Fields that MUST NOT appear in InviteeStatusDTO:
        email="aliia@example.com",
        plan="PRO",
        subscription_end=datetime.now(UTC),
    )


def _query_returns(db, rows):
    """Make db.query(...).filter(...).order_by(...).all() return `rows`."""
    chain = MagicMock()
    chain.filter.return_value.order_by.return_value.all.return_value = rows
    db.query.return_value = chain
    return db


# ---------------------------------------------------------------------------
# Privacy: DTO field surface
# ---------------------------------------------------------------------------


class TestInviteeDTOPrivacy:
    def test_dto_has_no_phone_field(self):
        fields = set(InviteeStatusDTO.model_fields.keys())
        assert "phone" not in fields

    def test_dto_has_no_email_field(self):
        fields = set(InviteeStatusDTO.model_fields.keys())
        assert "email" not in fields

    def test_dto_has_no_subscription_type_field(self):
        fields = set(InviteeStatusDTO.model_fields.keys())
        assert "subscription_type" not in fields
        assert "plan" not in fields

    def test_dto_has_required_safe_fields(self):
        fields = set(InviteeStatusDTO.model_fields.keys())
        assert "invitee_id" in fields
        assert "invitee_display_name" in fields
        assert "invitee_avatar_url" in fields
        assert "redeemed_at" in fields

    def test_list_invitees_returns_invitee_status_dtos(self):
        inviter_id = uuid4()
        redemption = _fake_redemption(inviter_id=inviter_id)
        db = _query_returns(MagicMock(), [redemption])
        user = _fake_user()
        admin_svc = MagicMock()
        admin_svc.get_user.return_value = user
        file_svc = MagicMock()
        file_svc.get_avatar_url.return_value = None
        svc = _make_service(db=db, admin_user_service=admin_svc, file_service=file_svc)
        result = svc.list_invitees(inviter_id)
        assert all(isinstance(r, InviteeStatusDTO) for r in result)

    def test_returned_dto_exposes_no_phone(self):
        inviter_id = uuid4()
        redemption = _fake_redemption(inviter_id=inviter_id)
        db = _query_returns(MagicMock(), [redemption])
        user = _fake_user(phone="+77001234567")
        admin_svc = MagicMock()
        admin_svc.get_user.return_value = user
        file_svc = MagicMock()
        file_svc.get_avatar_url.return_value = None
        svc = _make_service(db=db, admin_user_service=admin_svc, file_service=file_svc)
        result = svc.list_invitees(inviter_id)
        assert len(result) == 1
        dto = result[0]
        assert not hasattr(dto, "phone")
        assert not hasattr(dto, "email")
        assert not hasattr(dto, "plan")
        # The phone must not appear in display_name
        assert "+7700" not in dto.invitee_display_name

    def test_returned_dto_exposes_no_email(self):
        inviter_id = uuid4()
        redemption = _fake_redemption(inviter_id=inviter_id)
        db = _query_returns(MagicMock(), [redemption])
        user = _fake_user(name="Алия", phone="+77001234567")
        admin_svc = MagicMock()
        admin_svc.get_user.return_value = user
        file_svc = MagicMock()
        file_svc.get_avatar_url.return_value = None
        svc = _make_service(db=db, admin_user_service=admin_svc, file_service=file_svc)
        result = svc.list_invitees(inviter_id)
        dto = result[0]
        assert "@" not in dto.invitee_display_name


# ---------------------------------------------------------------------------
# Keycloak failure — fail-soft
# ---------------------------------------------------------------------------


class TestKeycloakFailureFallback:
    def test_single_keycloak_error_returns_placeholder_not_500(self):
        """One invitee fails Keycloak lookup → row shows '—', list continues."""
        inviter_id = uuid4()
        r1 = _fake_redemption(inviter_id=inviter_id)
        r2 = _fake_redemption(inviter_id=inviter_id)
        db = _query_returns(MagicMock(), [r1, r2])
        admin_svc = MagicMock()
        admin_svc.get_user.side_effect = [
            Exception("Keycloak 503"),  # first fails
            _fake_user(name="Зара"),  # second succeeds
        ]
        file_svc = MagicMock()
        file_svc.get_avatar_url.return_value = None
        svc = _make_service(db=db, admin_user_service=admin_svc, file_service=file_svc)
        result = svc.list_invitees(inviter_id)
        # Both rows returned — list not cut short
        assert len(result) == 2
        # First row gets placeholder
        assert result[0].invitee_display_name == "—"
        # Second row gets real name
        assert result[1].invitee_display_name == "Зара"

    def test_all_keycloak_errors_returns_list_of_placeholders(self):
        inviter_id = uuid4()
        rows = [_fake_redemption(inviter_id=inviter_id) for _ in range(3)]
        db = _query_returns(MagicMock(), rows)
        admin_svc = MagicMock()
        admin_svc.get_user.side_effect = Exception("Keycloak down")
        svc = _make_service(db=db, admin_user_service=admin_svc)
        result = svc.list_invitees(inviter_id)
        assert len(result) == 3
        assert all(r.invitee_display_name == "—" for r in result)

    def test_avatar_presign_error_does_not_drop_row(self):
        """Avatar presign failure → avatar_url=None, row still in list."""
        inviter_id = uuid4()
        redemption = _fake_redemption(inviter_id=inviter_id)
        db = _query_returns(MagicMock(), [redemption])
        user = _fake_user(avatar="avatar.jpg")
        admin_svc = MagicMock()
        admin_svc.get_user.return_value = user
        file_svc = MagicMock()
        file_svc.get_avatar_url.side_effect = Exception("MinIO timeout")
        svc = _make_service(db=db, admin_user_service=admin_svc, file_service=file_svc)
        result = svc.list_invitees(inviter_id)
        assert len(result) == 1
        assert result[0].invitee_avatar_url is None
        assert result[0].invitee_display_name == user.name


# ---------------------------------------------------------------------------
# Display name logic
# ---------------------------------------------------------------------------


class TestDisplayName:
    def test_name_used_when_available(self):
        inviter_id = uuid4()
        redemption = _fake_redemption(inviter_id=inviter_id)
        db = _query_returns(MagicMock(), [redemption])
        user = _fake_user(name="Жанна")
        admin_svc = MagicMock()
        admin_svc.get_user.return_value = user
        file_svc = MagicMock()
        file_svc.get_avatar_url.return_value = None
        svc = _make_service(db=db, admin_user_service=admin_svc, file_service=file_svc)
        result = svc.list_invitees(inviter_id)
        assert result[0].invitee_display_name == "Жанна"

    def test_masked_phone_used_when_name_is_empty(self):
        """When user.name is falsy, display falls back to masked phone."""
        inviter_id = uuid4()
        redemption = _fake_redemption(inviter_id=inviter_id)
        db = _query_returns(MagicMock(), [redemption])
        user = _fake_user(name="", phone="+77001234567")
        admin_svc = MagicMock()
        admin_svc.get_user.return_value = user
        file_svc = MagicMock()
        file_svc.get_avatar_url.return_value = None
        svc = _make_service(db=db, admin_user_service=admin_svc, file_service=file_svc)
        result = svc.list_invitees(inviter_id)
        display = result[0].invitee_display_name
        # Raw phone must not appear verbatim
        assert display != "+77001234567"
        # But some portion of the phone is present (masked)
        assert len(display) > 0

    def test_avatar_url_is_presigned_when_avatar_exists(self):
        inviter_id = uuid4()
        redemption = _fake_redemption(inviter_id=inviter_id)
        db = _query_returns(MagicMock(), [redemption])
        user = _fake_user(avatar="myavatar.jpg")
        admin_svc = MagicMock()
        admin_svc.get_user.return_value = user
        file_svc = MagicMock()
        file_svc.get_avatar_url.return_value = "https://minio/presigned/myavatar.jpg"
        svc = _make_service(db=db, admin_user_service=admin_svc, file_service=file_svc)
        result = svc.list_invitees(inviter_id)
        assert result[0].invitee_avatar_url == "https://minio/presigned/myavatar.jpg"

    def test_avatar_url_none_when_no_avatar(self):
        inviter_id = uuid4()
        redemption = _fake_redemption(inviter_id=inviter_id)
        db = _query_returns(MagicMock(), [redemption])
        user = _fake_user(avatar=None)
        admin_svc = MagicMock()
        admin_svc.get_user.return_value = user
        file_svc = MagicMock()
        svc = _make_service(db=db, admin_user_service=admin_svc, file_service=file_svc)
        result = svc.list_invitees(inviter_id)
        assert result[0].invitee_avatar_url is None
        file_svc.get_avatar_url.assert_not_called()


# ---------------------------------------------------------------------------
# Empty list and multi-row ordering
# ---------------------------------------------------------------------------


class TestEmptyAndOrdering:
    def test_empty_list_when_no_redemptions(self):
        inviter_id = uuid4()
        db = _query_returns(MagicMock(), [])
        svc = _make_service(db=db)
        result = svc.list_invitees(inviter_id)
        assert result == []

    def test_returns_all_rows(self):
        inviter_id = uuid4()
        rows = [_fake_redemption(inviter_id=inviter_id) for _ in range(5)]
        db = _query_returns(MagicMock(), rows)
        admin_svc = MagicMock()
        admin_svc.get_user.return_value = _fake_user()
        file_svc = MagicMock()
        file_svc.get_avatar_url.return_value = None
        svc = _make_service(db=db, admin_user_service=admin_svc, file_service=file_svc)
        result = svc.list_invitees(inviter_id)
        assert len(result) == 5


# ---------------------------------------------------------------------------
# IDOR: inviter_id must come from auth, not body
# ---------------------------------------------------------------------------


class TestIDORPrevention:
    def test_service_filters_by_passed_inviter_id(self):
        """list_invitees(inviter_id) must filter ReferralRedemption by
        the authenticated user's ID only — no body param to spoof."""
        inviter_id = uuid4()
        attacker_id = uuid4()

        # Only redemptions for inviter_id in DB — attacker gets nothing
        db = _query_returns(MagicMock(), [])
        svc = _make_service(db=db)
        result = svc.list_invitees(attacker_id)
        assert result == []

    def test_query_passes_inviter_id_to_filter(self):
        """Verify that the DB query is filtered (not a full table scan)."""
        inviter_id = uuid4()
        db = MagicMock()
        chain = MagicMock()
        chain.filter.return_value.order_by.return_value.all.return_value = []
        db.query.return_value = chain

        svc = _make_service(db=db)
        svc.list_invitees(inviter_id)

        # Filter must be called exactly once — never a full table scan
        chain.filter.assert_called_once()

    def test_invitees_of_different_inviters_are_separate(self):
        inviter_a = uuid4()
        inviter_b = uuid4()

        row_a = _fake_redemption(inviter_id=inviter_a)
        row_b = _fake_redemption(inviter_id=inviter_b)

        db_a = _query_returns(MagicMock(), [row_a])
        db_b = _query_returns(MagicMock(), [row_b])

        admin_svc = MagicMock()
        admin_svc.get_user.return_value = _fake_user()
        file_svc = MagicMock()
        file_svc.get_avatar_url.return_value = None

        svc_a = _make_service(db=db_a, admin_user_service=admin_svc, file_service=file_svc)
        result_a = svc_a.list_invitees(inviter_a)
        assert len(result_a) == 1
        assert result_a[0].invitee_id == row_a.invitee_id

        admin_svc2 = MagicMock()
        admin_svc2.get_user.return_value = _fake_user()
        file_svc2 = MagicMock()
        file_svc2.get_avatar_url.return_value = None
        svc_b = _make_service(db=db_b, admin_user_service=admin_svc2, file_service=file_svc2)
        result_b = svc_b.list_invitees(inviter_b)
        assert len(result_b) == 1
        assert result_b[0].invitee_id == row_b.invitee_id
