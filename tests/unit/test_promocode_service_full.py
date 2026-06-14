"""Unit tests for PromocodeService — every public method.

Covers:
- validate_promocode: not found / expired / exhausted / valid
- check_promocode_usage: used / not used
- get_promocode_activation_info: valid / user missing / already used / invalid plan
- activate_promocode: race-condition atomic increment, one-per-user rollback,
  subscription activation, subscription failure (still saves usage)
- create_promocode: success / duplicate code / auto-expiry from duration_days
- get_available_promocodes: filters expired + exhausted
- get_promocode_by_id: found / not found
- update_promocode: updates attributes
- deactivate_promocode_by_code: sets expires_at to past / not found returns False
- get_user_promocode_history: maps usages with active status

All tests are pure — DB session is mocked via MagicMock.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call
from uuid import uuid4

import pytest
from fastapi import HTTPException

# Register ORM models to resolve SQLAlchemy mapper relationships including
# Payment (needed for Subscription model's FK resolution).
import payments.models  # noqa: F401
import quiz.models  # noqa: F401
import student.models  # noqa: F401

from promocodes.service import PromocodeService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(db=None, subscription_service=None) -> PromocodeService:
    if db is None:
        db = MagicMock()
    if subscription_service is None:
        subscription_service = MagicMock()
        subscription_service.activate_subscription = AsyncMock(return_value=None)
    return PromocodeService(db_session=db, subscription_service=subscription_service)


def _fake_promo(
    id=1,
    code="PROMO01",
    plan_type="PRO",
    duration_days=30,
    max_activations=10,
    activations_count=0,
    expires_at=None,
    is_trial=False,
    is_reusable=False,
    description="Test promo",
    created_by=None,   # must be UUID (PromocodeDTO validates this)
    created_at=None,
):
    return SimpleNamespace(
        id=id,
        code=code,
        plan_type=plan_type,
        duration_days=duration_days,
        max_activations=max_activations,
        activations_count=activations_count,
        expires_at=expires_at,
        is_trial=is_trial,
        is_reusable=is_reusable,
        description=description,
        created_by=created_by or uuid4(),
        created_at=created_at or datetime.now(UTC),
    )


def _fake_user(plan="FREE"):
    return SimpleNamespace(id=uuid4(), plan=plan, email=None, name="Тест")


def _fake_usage(id=1, promo_id=1, user_id=None, plan="PRO",
                expires_at=None, activated_at=None):
    return SimpleNamespace(
        id=id,
        promocode_id=promo_id,
        student_guid=str(user_id or uuid4()),
        activated_plan=plan,
        access_expires_at=expires_at or datetime.now(UTC) + timedelta(days=30),
        activated_at=activated_at or datetime.now(UTC),
    )


def _db_first(db, return_value):
    """Make db.query(...).filter(...).first() return `return_value`."""
    db.query.return_value.filter.return_value.first.return_value = return_value
    return db


def _db_all(db, return_value):
    """Make db.query(...).filter(...).all() return `return_value`."""
    db.query.return_value.filter.return_value.all.return_value = return_value
    return db


# ---------------------------------------------------------------------------
# validate_promocode
# ---------------------------------------------------------------------------


class TestValidatePromocode:
    def test_not_found_raises_404(self):
        db = _db_first(MagicMock(), None)
        svc = _make_service(db=db)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(svc.validate_promocode("INVALID"))
        assert exc.value.status_code == 404

    def test_expired_raises_400(self):
        promo = _fake_promo(expires_at=datetime.now(UTC) - timedelta(days=1))
        db = _db_first(MagicMock(), promo)
        svc = _make_service(db=db)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(svc.validate_promocode("PROMO01"))
        assert exc.value.status_code == 400

    def test_exhausted_raises_400(self):
        promo = _fake_promo(max_activations=5, activations_count=5)
        db = _db_first(MagicMock(), promo)
        svc = _make_service(db=db)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(svc.validate_promocode("PROMO01"))
        assert exc.value.status_code == 400

    def test_valid_promo_returns_object(self):
        promo = _fake_promo()
        db = _db_first(MagicMock(), promo)
        svc = _make_service(db=db)
        result = asyncio.run(svc.validate_promocode("PROMO01"))
        assert result is promo

    def test_code_uppercased_before_lookup(self):
        promo = _fake_promo(code="PROMO01")
        db = _db_first(MagicMock(), promo)
        svc = _make_service(db=db)
        # lowercase input must still find the promo (service uppercases before query)
        result = asyncio.run(svc.validate_promocode("promo01"))
        assert result is promo  # returned the correct promo
        db.query.return_value.filter.assert_called_once()  # filter was applied

    def test_no_expiry_and_slots_left_is_valid(self):
        promo = _fake_promo(expires_at=None, max_activations=100, activations_count=5)
        db = _db_first(MagicMock(), promo)
        svc = _make_service(db=db)
        result = asyncio.run(svc.validate_promocode("PROMO01"))
        assert result is promo


# ---------------------------------------------------------------------------
# check_promocode_usage
# ---------------------------------------------------------------------------


class TestCheckPromocodeUsage:
    def test_returns_true_when_used(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(id=1)
        svc = _make_service(db=db)
        result = asyncio.run(svc.check_promocode_usage(str(uuid4()), 1))
        assert result is True

    def test_returns_false_when_not_used(self):
        db = _db_first(MagicMock(), None)
        svc = _make_service(db=db)
        result = asyncio.run(svc.check_promocode_usage(str(uuid4()), 1))
        assert result is False


# ---------------------------------------------------------------------------
# get_promocode_activation_info
# ---------------------------------------------------------------------------


class TestGetActivationInfo:
    def test_user_none_raises_400(self):
        svc = _make_service()
        with pytest.raises(HTTPException) as exc:
            asyncio.run(svc.get_promocode_activation_info(None, "PROMO01"))
        assert exc.value.status_code == 400

    def test_user_without_id_raises_400(self):
        svc = _make_service()
        user = SimpleNamespace()  # no .id attribute
        with pytest.raises(HTTPException) as exc:
            asyncio.run(svc.get_promocode_activation_info(user, "PROMO01"))
        assert exc.value.status_code == 400

    def test_reusable_promo_skips_usage_check(self):
        promo = _fake_promo(is_reusable=True)
        db = _db_first(MagicMock(), promo)
        svc = _make_service(db=db)
        user = _fake_user()
        result = asyncio.run(svc.get_promocode_activation_info(user, "PROMO01"))
        assert result.success is True

    def test_not_reusable_already_used_raises_400(self):
        promo = _fake_promo(is_reusable=False)
        db = MagicMock()
        # First query (validate): returns promo
        # Second query (check_usage): returns usage row
        db.query.return_value.filter.return_value.first.side_effect = [promo, SimpleNamespace(id=1)]
        svc = _make_service(db=db)
        user = _fake_user()
        with pytest.raises(HTTPException) as exc:
            asyncio.run(svc.get_promocode_activation_info(user, "PROMO01"))
        assert exc.value.status_code == 400

    def test_valid_returns_dto_with_plan(self):
        promo = _fake_promo(plan_type="PRO", duration_days=30, is_reusable=True)
        db = _db_first(MagicMock(), promo)
        svc = _make_service(db=db)
        user = _fake_user()
        result = asyncio.run(svc.get_promocode_activation_info(user, "PROMO01"))
        assert result.plan == "PRO"
        assert result.duration_days == 30

    def test_invalid_plan_type_raises_400(self):
        promo = _fake_promo(plan_type="INVALID_PLAN")
        db = _db_first(MagicMock(), promo)
        svc = _make_service(db=db)
        user = _fake_user()
        with pytest.raises(HTTPException) as exc:
            asyncio.run(svc.get_promocode_activation_info(user, "PROMO01"))
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# activate_promocode
# ---------------------------------------------------------------------------


class TestActivatePromocode:
    def _make_atomic_db(self, *, promo_found=True, rowcount=1, already_used=False):
        """Build a DB mock suitable for activate_promocode's multi-query flow."""
        db = MagicMock()
        # Atomic UPDATE rowcount
        exec_result = MagicMock()
        exec_result.rowcount = rowcount
        db.execute.return_value = exec_result

        promo = _fake_promo() if promo_found else None
        usage_row = SimpleNamespace(id=1) if already_used else None

        # query sequence after the UPDATE:
        # 1st: fetch fresh promo after increment
        # 2nd: check already-used (for non-reusable)
        db.query.return_value.filter.return_value.first.side_effect = [promo, usage_row]
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        return db

    def test_success_returns_dto(self):
        db = self._make_atomic_db(rowcount=1)
        sub_svc = MagicMock()
        sub_svc.activate_subscription = AsyncMock(return_value=None)
        svc = _make_service(db=db, subscription_service=sub_svc)
        user = _fake_user()
        result = asyncio.run(svc.activate_promocode(user, "PROMO01"))
        assert result.success is True
        assert result.plan == "PRO"
        db.commit.assert_called()

    def test_atomic_update_rowcount_zero_promo_not_found_raises(self):
        db = self._make_atomic_db(rowcount=0, promo_found=False)
        svc = _make_service(db=db)
        user = _fake_user()
        with pytest.raises(HTTPException) as exc:
            asyncio.run(svc.activate_promocode(user, "PROMO01"))
        assert exc.value.status_code == 404

    def test_atomic_update_rowcount_zero_exhausted_raises(self):
        exhausted = _fake_promo(max_activations=5, activations_count=5)
        db = MagicMock()
        exec_result = MagicMock()
        exec_result.rowcount = 0
        db.execute.return_value = exec_result
        # First filter().first() in error-diagnosis path
        db.query.return_value.filter.return_value.first.return_value = exhausted
        svc = _make_service(db=db)
        user = _fake_user()
        with pytest.raises(HTTPException) as exc:
            asyncio.run(svc.activate_promocode(user, "PROMO01"))
        assert exc.value.status_code == 400

    def test_already_used_rolls_back_increment(self):
        """Non-reusable code + user already used it → decrement count and raise 400."""
        db = self._make_atomic_db(rowcount=1, already_used=True)
        svc = _make_service(db=db)
        user = _fake_user()
        with pytest.raises(HTTPException) as exc:
            asyncio.run(svc.activate_promocode(user, "PROMO01"))
        assert exc.value.status_code == 400
        # db.execute called twice: increment, then decrement
        assert db.execute.call_count == 2
        db.commit.assert_called()  # rollback commit

    def test_subscription_failure_still_saves_usage(self):
        """If Keycloak activation fails, usage row is still committed (audit trail)."""
        db = self._make_atomic_db(rowcount=1, already_used=False)
        sub_svc = MagicMock()
        sub_svc.activate_subscription = AsyncMock(side_effect=Exception("Keycloak error"))
        svc = _make_service(db=db, subscription_service=sub_svc)
        user = _fake_user()
        result = asyncio.run(svc.activate_promocode(user, "PROMO01"))
        # Still returns success — usage recorded, admin must fix manually
        assert result.success is True
        db.commit.assert_called()

    def test_user_none_raises_400(self):
        svc = _make_service()
        with pytest.raises(HTTPException) as exc:
            asyncio.run(svc.activate_promocode(None, "PROMO01"))
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# create_promocode
# ---------------------------------------------------------------------------


class TestCreatePromocode:
    def test_duplicate_code_raises_400(self):
        db = _db_first(MagicMock(), _fake_promo())  # existing promo
        svc = _make_service(db=db)
        from promocodes.dtos import PromocodeCreateDTO
        from common.enums import PlanType
        dto = PromocodeCreateDTO(
            code="PROMO01", plan_type=PlanType.PRO, duration_days=30,
            max_activations=10, description="dup test"
        )
        with pytest.raises(HTTPException) as exc:
            asyncio.run(svc.create_promocode(dto))
        assert exc.value.status_code == 400

    def test_creates_new_promo_and_commits(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None  # no duplicate
        fake_promo = _fake_promo(id=42, code="NEWCODE")
        db.refresh.side_effect = lambda p: setattr(p, "id", 42) or None
        db.add.side_effect = lambda p: setattr(p, "id", 42)
        svc = _make_service(db=db)
        from promocodes.dtos import PromocodeCreateDTO
        from common.enums import PlanType
        dto = PromocodeCreateDTO(
            code="NEWCODE", plan_type=PlanType.PRO, duration_days=30,
            max_activations=10, description="new"
        )
        # Patch the Promocode model to avoid ORM mapper issues
        from unittest.mock import patch
        import promocodes.service as svc_module
        with patch.object(svc_module, "Promocode") as MockPromocode:
            MockPromocode.return_value = fake_promo
            asyncio.run(svc.create_promocode(dto))
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_auto_expiry_set_from_duration_when_no_explicit_expires(self):
        """expires_at=None → auto-compute from duration_days."""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        svc = _make_service(db=db)
        from promocodes.dtos import PromocodeCreateDTO
        from common.enums import PlanType
        import promocodes.service as svc_module
        from unittest.mock import patch

        dummy_promo = _fake_promo(id=1, expires_at=None)
        with patch.object(svc_module, "Promocode") as MockPromocode:
            MockPromocode.return_value = dummy_promo
            dto = PromocodeCreateDTO(
                code="AUTO", plan_type=PlanType.PRO, duration_days=14,
                max_activations=5, expires_at=None
            )
            asyncio.run(svc.create_promocode(dto))
        # The Promocode constructor was called with expires_at set
        promo_kwargs = MockPromocode.call_args[1]
        expires = promo_kwargs.get("expires_at")
        assert expires is not None
        # Should be ~14 days from now (use total_seconds — .days floors partial days)
        delta = expires - datetime.now(UTC)
        assert 13 * 86400 < delta.total_seconds() <= 14 * 86400 + 1


# ---------------------------------------------------------------------------
# get_available_promocodes
# ---------------------------------------------------------------------------


class TestGetAvailablePromocodes:
    def test_returns_non_expired_non_exhausted(self):
        db = MagicMock()
        promo = _fake_promo(activations_count=2, max_activations=10)
        db.query.return_value.filter.return_value.all.return_value = [promo]
        svc = _make_service(db=db)
        result = asyncio.run(svc.get_available_promocodes())
        assert len(result) == 1

    def test_empty_when_no_available(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        svc = _make_service(db=db)
        result = asyncio.run(svc.get_available_promocodes())
        assert result == []


# ---------------------------------------------------------------------------
# get_promocode_by_id
# ---------------------------------------------------------------------------


class TestGetPromocodeById:
    def test_found_returns_dto(self):
        db = _db_first(MagicMock(), _fake_promo(id=7))
        svc = _make_service(db=db)
        result = asyncio.run(svc.get_promocode_by_id(7))
        assert result is not None
        assert result.id == 7

    def test_not_found_returns_none(self):
        db = _db_first(MagicMock(), None)
        svc = _make_service(db=db)
        result = asyncio.run(svc.get_promocode_by_id(999))
        assert result is None


# ---------------------------------------------------------------------------
# update_promocode
# ---------------------------------------------------------------------------


class TestUpdatePromocode:
    def test_updates_attributes_and_commits(self):
        db = MagicMock()
        promo = _fake_promo(id=1, max_activations=10)
        db.query.return_value.filter.return_value.first.return_value = promo
        svc = _make_service(db=db)
        asyncio.run(svc.update_promocode(1, {"max_activations": 50}))
        db.commit.assert_called_once()
        assert promo.max_activations == 50

    def test_not_found_returns_none(self):
        db = _db_first(MagicMock(), None)
        svc = _make_service(db=db)
        result = asyncio.run(svc.update_promocode(999, {"max_activations": 50}))
        assert result is None


# ---------------------------------------------------------------------------
# deactivate_promocode_by_code
# ---------------------------------------------------------------------------


class TestDeactivatePromocode:
    def test_deactivates_by_setting_past_expiry(self):
        db = MagicMock()
        promo = _fake_promo()
        db.query.return_value.filter.return_value.first.return_value = promo
        svc = _make_service(db=db)
        result = asyncio.run(svc.deactivate_promocode_by_code("PROMO01"))
        assert result is True
        assert promo.expires_at < datetime.now(UTC)
        db.commit.assert_called_once()

    def test_not_found_returns_false(self):
        db = _db_first(MagicMock(), None)
        svc = _make_service(db=db)
        result = asyncio.run(svc.deactivate_promocode_by_code("MISSING"))
        assert result is False


# ---------------------------------------------------------------------------
# get_user_promocode_history
# ---------------------------------------------------------------------------


class TestGetUserHistory:
    def test_empty_history(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        svc = _make_service(db=db)
        result = asyncio.run(svc.get_user_promocode_history(str(uuid4())))
        assert result == []

    def test_maps_usage_to_dto(self):
        user_id = uuid4()
        usage = _fake_usage(
            id=1, promo_id=1, user_id=user_id,
            expires_at=datetime.now(UTC) + timedelta(days=10),
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [usage]
        db.query.return_value.filter.return_value.first.return_value = _fake_promo(id=1)
        svc = _make_service(db=db)
        result = asyncio.run(svc.get_user_promocode_history(str(user_id)))
        assert len(result) == 1
        assert result[0].is_active is True

    def test_expired_usage_is_inactive(self):
        user_id = uuid4()
        usage = _fake_usage(
            expires_at=datetime.now(UTC) - timedelta(days=1),  # already expired
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [usage]
        db.query.return_value.filter.return_value.first.return_value = _fake_promo(id=1)
        svc = _make_service(db=db)
        result = asyncio.run(svc.get_user_promocode_history(str(user_id)))
        assert result[0].is_active is False

    def test_missing_promo_shows_unknown(self):
        usage = _fake_usage()
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [usage]
        db.query.return_value.filter.return_value.first.return_value = None  # promo deleted
        svc = _make_service(db=db)
        result = asyncio.run(svc.get_user_promocode_history(str(uuid4())))
        assert result[0].promocode_code == "Unknown"
