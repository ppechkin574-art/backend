"""Unit tests for AnalyticService.

Covers:
- save_event: no-meta succeeds, valid meta succeeds, invalid meta raises WrongEventMetaData
- get_audience: role/plan/grade bucketing (normalization, defaults, grade range)
- get_api_timing_summary: total_samples = sum(r.count), window_hours + filters forwarded
- get_payments_by_gateway: total_amount = Decimal sum of rows, window_hours preserved
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from analytics.dtos.api_timing import ApiTimingRowDTO
from analytics.dtos.enums import UserActivityEnum
from analytics.dtos.events import EventCreateServiceDTO
from analytics.dtos.payments_by_gateway import PaymentByGatewayRowDTO
from analytics.exceptions import WrongEventMetaData
from analytics.service import AnalyticService
from common.enums import PlanType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_uow() -> MagicMock:
    uow = MagicMock()
    uow.__enter__ = lambda s: s
    uow.__exit__ = MagicMock(return_value=False)
    return uow


def _passthrough_cache() -> MagicMock:
    cache = MagicMock()
    cache.get_or_set.side_effect = lambda key, fn, ttl: fn()
    return cache


def _make_service(uow=None, users=None, cache=None) -> AnalyticService:
    return AnalyticService(
        uow=uow or _make_uow(),
        users=users or MagicMock(),
        cache_service=cache or _passthrough_cache(),
    )


def _make_event(
    event_name: str = "app_opened",
    meta: dict | None = None,
) -> EventCreateServiceDTO:
    return EventCreateServiceDTO(
        device_id="dev-1",
        session_id="sess-1",
        event_name=event_name,
        event_time=datetime(2026, 6, 13, 12, 0, 0, tzinfo=UTC),
        meta=meta,
    )


def _fake_user(role=None, plan=None, grade=None) -> SimpleNamespace:
    attrs = SimpleNamespace(
        role=[role] if role is not None else None,
        plan=[plan] if plan is not None else None,
        grade=[grade] if grade is not None else None,
    )
    return SimpleNamespace(attributes=attrs)


def _fake_user_no_attrs() -> SimpleNamespace:
    return SimpleNamespace(attributes=None)


def _timing_row(endpoint: str, count: int) -> ApiTimingRowDTO:
    return ApiTimingRowDTO(endpoint=endpoint, count=count, p50_ms=10.0, p95_ms=50.0, avg_ms=20.0, error_rate=0.0)


def _gateway_row(gateway: str, count: int, total_amount: Decimal) -> PaymentByGatewayRowDTO:
    return PaymentByGatewayRowDTO(gateway=gateway, count=count, total_amount=total_amount)


def _svc_with_users(users: list) -> AnalyticService:
    users_repo = MagicMock()
    users_repo.identity_provider_client.get_all_users.return_value = users
    return _make_service(users=users_repo, cache=_passthrough_cache())


# ---------------------------------------------------------------------------
# save_event
# ---------------------------------------------------------------------------


class TestSaveEvent:
    def test_no_meta_saves_successfully(self):
        uow = _make_uow()
        svc = _make_service(uow=uow)
        svc.save_event(_make_event(event_name="app_opened", meta=None))
        uow.anlytic_repo.save_event.assert_called_once()

    def test_unknown_event_name_with_meta_saves_successfully(self):
        # case _ → pass → valid_meta stays True
        uow = _make_uow()
        svc = _make_service(uow=uow)
        svc.save_event(_make_event(event_name="unknown_event", meta={"whatever": 1}))
        uow.anlytic_repo.save_event.assert_called_once()

    def test_valid_meta_for_app_crashed_saves_successfully(self):
        uow = _make_uow()
        svc = _make_service(uow=uow)
        event = _make_event(
            event_name=UserActivityEnum.app_crashed.value,
            meta={"error": "NullPointerException"},
        )
        svc.save_event(event)
        uow.anlytic_repo.save_event.assert_called_once()

    def test_invalid_meta_for_app_crashed_raises(self):
        uow = _make_uow()
        svc = _make_service(uow=uow)
        event = _make_event(
            event_name=UserActivityEnum.app_crashed.value,
            meta={"wrong_field": "value"},  # missing required 'error'
        )
        with pytest.raises(WrongEventMetaData):
            svc.save_event(event)

    def test_valid_meta_for_user_registered_saves_successfully(self):
        uow = _make_uow()
        svc = _make_service(uow=uow)
        event = _make_event(
            event_name=UserActivityEnum.user_registered.value,
            meta={"method": "phone"},
        )
        svc.save_event(event)
        uow.anlytic_repo.save_event.assert_called_once()

    def test_invalid_meta_for_user_registered_raises(self):
        uow = _make_uow()
        svc = _make_service(uow=uow)
        event = _make_event(
            event_name=UserActivityEnum.user_registered.value,
            meta={"wrong_key": "value"},  # non-empty but missing required 'method'
        )
        with pytest.raises(WrongEventMetaData):
            svc.save_event(event)

    def test_save_event_called_before_meta_check(self):
        # repo.save_event is always called; WrongEventMetaData is raised AFTER
        uow = _make_uow()
        svc = _make_service(uow=uow)
        event = _make_event(
            event_name=UserActivityEnum.app_crashed.value,
            meta={"wrong_field": "value"},
        )
        with pytest.raises(WrongEventMetaData):
            svc.save_event(event)
        uow.anlytic_repo.save_event.assert_called_once()


# ---------------------------------------------------------------------------
# get_audience — bucketing logic
# ---------------------------------------------------------------------------


class TestGetAudience:
    def test_empty_user_list_returns_zero_total(self):
        result = _svc_with_users([]).get_audience()
        assert result.total == 0
        assert result.by_role == []
        assert result.by_plan == []
        assert result.by_grade == []

    def test_total_matches_user_count(self):
        users = [_fake_user(role="student") for _ in range(5)]
        result = _svc_with_users(users).get_audience()
        assert result.total == 5

    def test_no_attrs_role_defaults_to_user(self):
        result = _svc_with_users([_fake_user_no_attrs()]).get_audience()
        roles = {r.name: r.count for r in result.by_role}
        assert roles["user"] == 1

    def test_blank_role_defaults_to_user(self):
        result = _svc_with_users([_fake_user(role="")]).get_audience()
        roles = {r.name: r.count for r in result.by_role}
        assert roles["user"] == 1

    def test_whitespace_role_defaults_to_user(self):
        result = _svc_with_users([_fake_user(role="   ")]).get_audience()
        roles = {r.name: r.count for r in result.by_role}
        assert roles["user"] == 1

    def test_role_normalized_to_lowercase(self):
        result = _svc_with_users([_fake_user(role="STUDENT")]).get_audience()
        roles = {r.name: r.count for r in result.by_role}
        assert roles.get("student") == 1
        assert "STUDENT" not in roles

    def test_multiple_roles_counted_separately(self):
        users = [
            _fake_user(role="student"),
            _fake_user(role="student"),
            _fake_user(role="teacher"),
        ]
        result = _svc_with_users(users).get_audience()
        roles = {r.name: r.count for r in result.by_role}
        assert roles["student"] == 2
        assert roles["teacher"] == 1

    def test_no_attrs_plan_defaults_to_free(self):
        result = _svc_with_users([_fake_user_no_attrs()]).get_audience()
        plans = {p.name: p.count for p in result.by_plan}
        assert plans[PlanType.FREE.value] == 1

    def test_blank_plan_defaults_to_free(self):
        result = _svc_with_users([_fake_user(plan="")]).get_audience()
        plans = {p.name: p.count for p in result.by_plan}
        assert plans[PlanType.FREE.value] == 1

    def test_plan_normalized_to_uppercase(self):
        result = _svc_with_users([_fake_user(plan="pro")]).get_audience()
        plans = {p.name: p.count for p in result.by_plan}
        assert plans.get("PRO") == 1
        assert "pro" not in plans

    def test_mixed_plans(self):
        users = [
            _fake_user(plan="FREE"),
            _fake_user(plan="FREE"),
            _fake_user(plan="PRO"),
        ]
        result = _svc_with_users(users).get_audience()
        plans = {p.name: p.count for p in result.by_plan}
        assert plans["FREE"] == 2
        assert plans["PRO"] == 1

    def test_grade_1_is_valid(self):
        result = _svc_with_users([_fake_user(grade="1")]).get_audience()
        grades = {g.name: g.count for g in result.by_grade}
        assert grades["1 класс"] == 1

    def test_grade_11_is_valid(self):
        result = _svc_with_users([_fake_user(grade="11")]).get_audience()
        grades = {g.name: g.count for g in result.by_grade}
        assert grades["11 класс"] == 1

    def test_grade_0_is_invalid(self):
        result = _svc_with_users([_fake_user(grade="0")]).get_audience()
        grades = {g.name: g.count for g in result.by_grade}
        assert grades["не указан"] == 1

    def test_grade_12_is_invalid(self):
        result = _svc_with_users([_fake_user(grade="12")]).get_audience()
        grades = {g.name: g.count for g in result.by_grade}
        assert grades["не указан"] == 1

    def test_grade_non_numeric_is_invalid(self):
        result = _svc_with_users([_fake_user(grade="abc")]).get_audience()
        grades = {g.name: g.count for g in result.by_grade}
        assert grades["не указан"] == 1

    def test_no_grade_attr_defaults_to_not_specified(self):
        result = _svc_with_users([_fake_user_no_attrs()]).get_audience()
        grades = {g.name: g.count for g in result.by_grade}
        assert grades["не указан"] == 1

    def test_by_role_sorted_descending_by_count(self):
        users = [
            _fake_user(role="student"),
            _fake_user(role="student"),
            _fake_user(role="teacher"),
        ]
        result = _svc_with_users(users).get_audience()
        counts = [r.count for r in result.by_role]
        assert counts == sorted(counts, reverse=True)


# ---------------------------------------------------------------------------
# get_api_timing_summary
# ---------------------------------------------------------------------------


class TestGetApiTimingSummary:
    def test_empty_rows_total_samples_zero(self):
        uow = _make_uow()
        uow.anlytic_repo.get_api_timing_summary.return_value = []
        result = _make_service(uow=uow).get_api_timing_summary(hours=24)
        assert result.total_samples == 0
        assert result.window_hours == 24

    def test_total_samples_is_sum_of_counts(self):
        rows = [
            _timing_row("/user/login", 100),
            _timing_row("/quiz/trainer", 50),
            _timing_row("/quiz/ent", 25),
        ]
        uow = _make_uow()
        uow.anlytic_repo.get_api_timing_summary.return_value = rows
        result = _make_service(uow=uow).get_api_timing_summary(hours=24)
        assert result.total_samples == 175

    def test_window_hours_preserved(self):
        uow = _make_uow()
        uow.anlytic_repo.get_api_timing_summary.return_value = []
        result = _make_service(uow=uow).get_api_timing_summary(hours=48)
        assert result.window_hours == 48

    def test_rows_passed_through(self):
        rows = [_timing_row("/health", 10)]
        uow = _make_uow()
        uow.anlytic_repo.get_api_timing_summary.return_value = rows
        result = _make_service(uow=uow).get_api_timing_summary()
        assert result.rows == rows

    def test_filters_forwarded_to_repo(self):
        uow = _make_uow()
        uow.anlytic_repo.get_api_timing_summary.return_value = []
        _make_service(uow=uow).get_api_timing_summary(hours=12, platform="ios", app_version="2.0.0")
        uow.anlytic_repo.get_api_timing_summary.assert_called_once_with(12, "ios", "2.0.0")

    def test_single_row_total_equals_its_count(self):
        uow = _make_uow()
        uow.anlytic_repo.get_api_timing_summary.return_value = [_timing_row("/auth/login", 77)]
        result = _make_service(uow=uow).get_api_timing_summary()
        assert result.total_samples == 77


# ---------------------------------------------------------------------------
# get_payments_by_gateway
# ---------------------------------------------------------------------------


class TestGetPaymentsByGateway:
    def test_empty_rows_total_amount_zero(self):
        uow = _make_uow()
        uow.anlytic_repo.get_payments_by_gateway.return_value = []
        result = _make_service(uow=uow).get_payments_by_gateway(hours=720)
        assert result.total_amount == Decimal("0")
        assert result.window_hours == 720

    def test_total_amount_is_decimal_sum(self):
        rows = [
            _gateway_row("freedompay", 10, Decimal("49900")),
            _gateway_row("google_play", 5, Decimal("24950")),
        ]
        uow = _make_uow()
        uow.anlytic_repo.get_payments_by_gateway.return_value = rows
        result = _make_service(uow=uow).get_payments_by_gateway()
        assert result.total_amount == Decimal("74850")

    def test_window_hours_preserved(self):
        uow = _make_uow()
        uow.anlytic_repo.get_payments_by_gateway.return_value = []
        result = _make_service(uow=uow).get_payments_by_gateway(hours=168)
        assert result.window_hours == 168

    def test_rows_passed_through(self):
        rows = [_gateway_row("freedompay", 3, Decimal("14970"))]
        uow = _make_uow()
        uow.anlytic_repo.get_payments_by_gateway.return_value = rows
        result = _make_service(uow=uow).get_payments_by_gateway()
        assert result.rows == rows

    def test_single_gateway_amount_exact(self):
        uow = _make_uow()
        uow.anlytic_repo.get_payments_by_gateway.return_value = [
            _gateway_row("google_play", 1, Decimal("4990"))
        ]
        result = _make_service(uow=uow).get_payments_by_gateway()
        assert result.total_amount == Decimal("4990")

    def test_decimal_precision_preserved(self):
        rows = [
            _gateway_row("freedompay", 1, Decimal("999.99")),
            _gateway_row("google_play", 1, Decimal("0.01")),
        ]
        uow = _make_uow()
        uow.anlytic_repo.get_payments_by_gateway.return_value = rows
        result = _make_service(uow=uow).get_payments_by_gateway()
        assert result.total_amount == Decimal("1000.00")
