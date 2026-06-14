"""Unit tests for SubscriptionPlanService.

Covers:
- get_plan_by_id: found / not found (404)
- get_plan_by_type: found / not found (404 with plan type in detail)
- create_plan: success / duplicate type (400) / price<=0 (400) / original_price invalid (400)
- update_plan: success / plan not found (404) / duplicate type (400) / price<=0 (400)
- calculate_price_for_months: 30-day plan (linear) / non-30-day plan (per-day rate)

All tests are pure — repository is mocked.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from common.enums import PlanType
from subscription.plan_service import SubscriptionPlanService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(repo=None) -> SubscriptionPlanService:
    return SubscriptionPlanService(plan_repository=repo or MagicMock())


def _fake_plan(id=1, plan_type=PlanType.PRO, price=4990, duration_days=30,
               original_price=None, is_active=True):
    return SimpleNamespace(
        id=id,
        plan_type=plan_type,
        price=Decimal(str(price)),
        original_price=Decimal(str(original_price)) if original_price else None,
        duration_days=duration_days,
        is_active=is_active,
    )


# ---------------------------------------------------------------------------
# get_plan_by_id
# ---------------------------------------------------------------------------


class TestGetPlanById:
    def test_found_returns_plan(self):
        repo = MagicMock()
        plan = _fake_plan(id=1)
        repo.get_plan_by_id.return_value = plan
        svc = _make_service(repo=repo)
        result = svc.get_plan_by_id(1)
        assert result is plan

    def test_not_found_raises_404(self):
        repo = MagicMock()
        repo.get_plan_by_id.return_value = None
        svc = _make_service(repo=repo)
        with pytest.raises(HTTPException) as exc:
            svc.get_plan_by_id(99)
        assert exc.value.status_code == 404

    def test_calls_repo_with_correct_id(self):
        repo = MagicMock()
        repo.get_plan_by_id.return_value = _fake_plan()
        svc = _make_service(repo=repo)
        svc.get_plan_by_id(42)
        repo.get_plan_by_id.assert_called_once_with(42)


# ---------------------------------------------------------------------------
# get_plan_by_type
# ---------------------------------------------------------------------------


class TestGetPlanByType:
    def test_found_returns_plan(self):
        repo = MagicMock()
        plan = _fake_plan(plan_type=PlanType.PRO)
        repo.get_plan_by_type.return_value = plan
        svc = _make_service(repo=repo)
        result = svc.get_plan_by_type(PlanType.PRO)
        assert result is plan

    def test_not_found_raises_404(self):
        repo = MagicMock()
        repo.get_plan_by_type.return_value = None
        svc = _make_service(repo=repo)
        with pytest.raises(HTTPException) as exc:
            svc.get_plan_by_type(PlanType.FREE)
        assert exc.value.status_code == 404

    def test_not_found_detail_contains_plan_type(self):
        repo = MagicMock()
        repo.get_plan_by_type.return_value = None
        svc = _make_service(repo=repo)
        with pytest.raises(HTTPException) as exc:
            svc.get_plan_by_type(PlanType.PRO)
        assert "PRO" in exc.value.detail or "pro" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# create_plan
# ---------------------------------------------------------------------------


class TestCreatePlan:
    def test_success_delegates_to_repo(self):
        repo = MagicMock()
        repo.get_plan_by_type.return_value = None  # no duplicate
        plan = _fake_plan()
        repo.create_plan.return_value = plan
        svc = _make_service(repo=repo)
        data = {"plan_type": PlanType.PRO, "price": 4990, "duration_days": 30}
        result = svc.create_plan(data)
        assert result is plan
        repo.create_plan.assert_called_once_with(data)

    def test_duplicate_type_raises_400(self):
        repo = MagicMock()
        repo.get_plan_by_type.return_value = _fake_plan()  # already exists
        svc = _make_service(repo=repo)
        with pytest.raises(HTTPException) as exc:
            svc.create_plan({"plan_type": PlanType.PRO, "price": 4990, "duration_days": 30})
        assert exc.value.status_code == 400

    def test_zero_price_raises_400(self):
        repo = MagicMock()
        repo.get_plan_by_type.return_value = None
        svc = _make_service(repo=repo)
        with pytest.raises(HTTPException) as exc:
            svc.create_plan({"plan_type": PlanType.FREE, "price": 0, "duration_days": 30})
        assert exc.value.status_code == 400
        assert "positive" in exc.value.detail.lower()

    def test_negative_price_raises_400(self):
        repo = MagicMock()
        repo.get_plan_by_type.return_value = None
        svc = _make_service(repo=repo)
        with pytest.raises(HTTPException) as exc:
            svc.create_plan({"plan_type": PlanType.FREE, "price": -100, "duration_days": 30})
        assert exc.value.status_code == 400

    def test_original_price_equal_to_price_raises_400(self):
        repo = MagicMock()
        repo.get_plan_by_type.return_value = None
        svc = _make_service(repo=repo)
        with pytest.raises(HTTPException) as exc:
            svc.create_plan({
                "plan_type": PlanType.PRO, "price": 4990,
                "original_price": 4990, "duration_days": 30
            })
        assert exc.value.status_code == 400

    def test_original_price_less_than_price_raises_400(self):
        repo = MagicMock()
        repo.get_plan_by_type.return_value = None
        svc = _make_service(repo=repo)
        with pytest.raises(HTTPException) as exc:
            svc.create_plan({
                "plan_type": PlanType.PRO, "price": 4990,
                "original_price": 3000, "duration_days": 30
            })
        assert exc.value.status_code == 400

    def test_original_price_greater_than_price_allowed(self):
        repo = MagicMock()
        repo.get_plan_by_type.return_value = None
        repo.create_plan.return_value = _fake_plan(original_price=9990)
        svc = _make_service(repo=repo)
        # original_price=9990 > price=4990 → valid discount
        svc.create_plan({
            "plan_type": PlanType.PRO, "price": 4990,
            "original_price": 9990, "duration_days": 30
        })
        repo.create_plan.assert_called_once()

    def test_no_original_price_skips_validation(self):
        repo = MagicMock()
        repo.get_plan_by_type.return_value = None
        repo.create_plan.return_value = _fake_plan()
        svc = _make_service(repo=repo)
        svc.create_plan({"plan_type": PlanType.FREE, "price": 1, "duration_days": 30})
        repo.create_plan.assert_called_once()


# ---------------------------------------------------------------------------
# update_plan
# ---------------------------------------------------------------------------


class TestUpdatePlan:
    def test_success_returns_updated_plan(self):
        repo = MagicMock()
        existing = _fake_plan(id=1, plan_type=PlanType.PRO)
        updated = _fake_plan(id=1, price=5990)
        repo.get_plan_by_id.return_value = existing
        repo.get_plan_by_type.return_value = None
        repo.update_plan.return_value = updated
        svc = _make_service(repo=repo)
        result = svc.update_plan(1, {"price": 5990})
        assert result is updated

    def test_plan_not_found_raises_404(self):
        repo = MagicMock()
        repo.get_plan_by_id.return_value = None
        svc = _make_service(repo=repo)
        with pytest.raises(HTTPException) as exc:
            svc.update_plan(99, {"price": 4990})
        assert exc.value.status_code == 404

    def test_update_to_duplicate_type_raises_400(self):
        repo = MagicMock()
        existing = _fake_plan(id=1, plan_type=PlanType.FREE)
        other = _fake_plan(id=2, plan_type=PlanType.PRO)  # PRO already exists
        repo.get_plan_by_id.return_value = existing
        repo.get_plan_by_type.return_value = other  # clash with plan id=2
        svc = _make_service(repo=repo)
        with pytest.raises(HTTPException) as exc:
            svc.update_plan(1, {"plan_type": PlanType.PRO})
        assert exc.value.status_code == 400

    def test_update_plan_type_to_same_id_allowed(self):
        # Changing type to one owned by SAME plan → no conflict
        repo = MagicMock()
        existing = _fake_plan(id=1, plan_type=PlanType.PRO)
        repo.get_plan_by_id.return_value = existing
        repo.get_plan_by_type.return_value = existing  # same plan!
        repo.update_plan.return_value = existing
        svc = _make_service(repo=repo)
        # Should not raise
        svc.update_plan(1, {"plan_type": PlanType.PRO})
        repo.update_plan.assert_called_once()

    def test_zero_price_in_update_raises_400(self):
        repo = MagicMock()
        repo.get_plan_by_id.return_value = _fake_plan(id=1)
        svc = _make_service(repo=repo)
        with pytest.raises(HTTPException) as exc:
            svc.update_plan(1, {"price": 0})
        assert exc.value.status_code == 400

    def test_repo_returns_none_raises_404(self):
        repo = MagicMock()
        repo.get_plan_by_id.return_value = _fake_plan(id=1)
        repo.get_plan_by_type.return_value = None
        repo.update_plan.return_value = None  # repo signals "not found"
        svc = _make_service(repo=repo)
        with pytest.raises(HTTPException) as exc:
            svc.update_plan(1, {"price": 4990})
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# calculate_price_for_months
# ---------------------------------------------------------------------------


class TestCalculatePriceForMonths:
    def test_30_day_plan_linear_price(self):
        """price × months for 30-day duration."""
        plan = _fake_plan(price=4990, duration_days=30)
        svc = _make_service()
        result = svc.calculate_price_for_months(plan, months=3)
        assert result == Decimal("4990") * 3

    def test_30_day_plan_1_month(self):
        plan = _fake_plan(price=4990, duration_days=30)
        svc = _make_service()
        assert svc.calculate_price_for_months(plan, months=1) == Decimal("4990")

    def test_90_day_plan_price_per_day_rate(self):
        """Non-30-day plan: price/duration * (months * 30)."""
        plan = _fake_plan(price=9990, duration_days=90)
        svc = _make_service()
        # price_per_day = 9990/90 = 111
        # result = 111 * (1 * 30) = 3330
        result = svc.calculate_price_for_months(plan, months=1)
        expected = Decimal("9990") / 90 * 30
        assert abs(result - expected) < Decimal("0.01")

    def test_365_day_plan_per_day_rate(self):
        plan = _fake_plan(price=36500, duration_days=365)
        svc = _make_service()
        result = svc.calculate_price_for_months(plan, months=1)
        # price_per_day = 36500/365 = 100
        # 100 * 30 = 3000
        expected = Decimal("36500") / 365 * 30
        assert abs(result - expected) < Decimal("0.01")

    def test_6_months_linear(self):
        plan = _fake_plan(price=1000, duration_days=30)
        svc = _make_service()
        assert svc.calculate_price_for_months(plan, months=6) == Decimal("6000")
