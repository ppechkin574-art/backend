"""Unit tests for PointsCalculatorService — the configurable leaderboard
points engine added in feature/backend-points-policy.

Tests cover:
- calculate_amount(): fixed mode, score_based mode, min_score_percent threshold
- passes_repeat_check(): always / first_only / improvement_only
- award_for_activity(): idempotency, policy disabled/missing, end-to-end flow

All tests are pure — no DB, no network. The UoW and audit-log queries
are mocked with MagicMock.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from quiz.services.points_calculator import PointsCalculatorService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _policy(
    activity_type: str = "ent_full",
    is_enabled: bool = True,
    mode: str = "score_based",
    fixed_points: int | None = None,
    score_multiplier: float | None = 1.0,
    min_score_percent: int = 0,
    repeat_mode: str = "always",
) -> SimpleNamespace:
    """Lightweight PointsPolicy stand-in. No ORM needed."""
    return SimpleNamespace(
        activity_type=activity_type,
        is_enabled=is_enabled,
        mode=mode,
        fixed_points=fixed_points,
        score_multiplier=score_multiplier,
        min_score_percent=min_score_percent,
        repeat_mode=repeat_mode,
    )


def _make_uow(
    policy=None,
    audit_first_result=None,   # return value of first .query(...).filter(...).first()
    audit_order_result=None,   # return value of .query(...).filter(...).order_by(...).first()
):
    """Build a mock UoW that the PointsCalculatorService can call."""
    uow = MagicMock()
    uow.points_policies = MagicMock()
    uow.points_policies.get_by_activity_type.return_value = policy
    uow.user_points = MagicMock()

    # Session mock for audit log queries
    session = MagicMock()
    # All query chains default to "no result found"
    chain = MagicMock()
    chain.filter.return_value.first.return_value = audit_first_result
    chain.filter.return_value.order_by.return_value.first.return_value = audit_order_result
    session.query.return_value = chain
    uow.session = session
    return uow


# ---------------------------------------------------------------------------
# calculate_amount
# ---------------------------------------------------------------------------


class TestCalculateAmount:
    calc = PointsCalculatorService()

    def test_score_based_multiplier_1_returns_score(self):
        p = _policy(mode="score_based", score_multiplier=1.0)
        assert self.calc.calculate_amount(p, score=120, total_questions=140) == 120

    def test_score_based_multiplier_half(self):
        p = _policy(mode="score_based", score_multiplier=0.5)
        assert self.calc.calculate_amount(p, score=100, total_questions=140) == 50

    def test_score_based_multiplier_2x(self):
        p = _policy(mode="score_based", score_multiplier=2.0)
        assert self.calc.calculate_amount(p, score=50, total_questions=140) == 100

    def test_score_based_none_multiplier_defaults_to_1(self):
        p = _policy(mode="score_based", score_multiplier=None)
        assert self.calc.calculate_amount(p, score=80, total_questions=140) == 80

    def test_fixed_mode_returns_fixed_points(self):
        p = _policy(mode="fixed", fixed_points=10, score_multiplier=None)
        assert self.calc.calculate_amount(p, score=999, total_questions=10) == 10

    def test_fixed_mode_zero_returns_zero(self):
        p = _policy(mode="fixed", fixed_points=0)
        assert self.calc.calculate_amount(p, score=100, total_questions=10) == 0

    def test_fixed_mode_none_fixed_points_returns_zero(self):
        p = _policy(mode="fixed", fixed_points=None)
        assert self.calc.calculate_amount(p, score=100, total_questions=10) == 0

    def test_score_zero_with_score_based_returns_zero(self):
        p = _policy(mode="score_based", score_multiplier=2.0)
        assert self.calc.calculate_amount(p, score=0, total_questions=140) == 0

    def test_score_based_never_returns_negative(self):
        p = _policy(mode="score_based", score_multiplier=-1.0)
        assert self.calc.calculate_amount(p, score=100, total_questions=140) == 0

    # min_score_percent threshold
    def test_below_min_score_percent_returns_zero(self):
        p = _policy(mode="fixed", fixed_points=10, min_score_percent=50)
        # 4/10 = 40% < 50% threshold
        assert self.calc.calculate_amount(p, score=4, total_questions=10) == 0

    def test_at_min_score_percent_returns_points(self):
        p = _policy(mode="fixed", fixed_points=10, min_score_percent=50)
        # 5/10 = 50% == threshold → should award
        assert self.calc.calculate_amount(p, score=5, total_questions=10) == 10

    def test_above_min_score_percent_returns_points(self):
        p = _policy(mode="fixed", fixed_points=10, min_score_percent=50)
        assert self.calc.calculate_amount(p, score=8, total_questions=10) == 10

    def test_min_score_zero_always_awards(self):
        p = _policy(mode="fixed", fixed_points=5, min_score_percent=0)
        assert self.calc.calculate_amount(p, score=0, total_questions=10) == 5

    def test_total_questions_zero_skips_pct_check(self):
        """Division-by-zero guard: if no questions, skip percent check."""
        p = _policy(mode="fixed", fixed_points=5, min_score_percent=80)
        assert self.calc.calculate_amount(p, score=0, total_questions=0) == 5

    def test_min_score_100_requires_perfect(self):
        p = _policy(mode="fixed", fixed_points=20, min_score_percent=100)
        assert self.calc.calculate_amount(p, score=9, total_questions=10) == 0
        assert self.calc.calculate_amount(p, score=10, total_questions=10) == 20


# ---------------------------------------------------------------------------
# passes_repeat_check
# ---------------------------------------------------------------------------


class TestPassesRepeatCheck:
    calc = PointsCalculatorService()
    user_id = uuid4()

    def test_always_returns_true_no_history(self):
        p = _policy(repeat_mode="always")
        uow = _make_uow(policy=p, audit_first_result=None)
        assert self.calc.passes_repeat_check(p, self.user_id, 100, uow) is True

    def test_always_returns_true_even_with_history(self):
        p = _policy(repeat_mode="always")
        uow = _make_uow(policy=p, audit_first_result=(1,))  # has history
        assert self.calc.passes_repeat_check(p, self.user_id, 100, uow) is True

    def test_first_only_returns_true_no_history(self):
        p = _policy(repeat_mode="first_only")
        uow = _make_uow(policy=p, audit_first_result=None)
        assert self.calc.passes_repeat_check(p, self.user_id, 100, uow) is True

    def test_first_only_returns_false_has_history(self):
        p = _policy(repeat_mode="first_only")
        uow = _make_uow(policy=p, audit_first_result=(1,))  # already received once
        assert self.calc.passes_repeat_check(p, self.user_id, 100, uow) is False

    def test_improvement_only_returns_true_no_history(self):
        """First ever attempt — no previous best — always True."""
        p = _policy(repeat_mode="improvement_only")
        uow = _make_uow(policy=p, audit_order_result=None)
        assert self.calc.passes_repeat_check(p, self.user_id, 50, uow) is True

    def test_improvement_only_returns_true_when_better_than_best(self):
        p = _policy(repeat_mode="improvement_only")
        uow = _make_uow(policy=p, audit_order_result=(100,))  # prev best = 100
        assert self.calc.passes_repeat_check(p, self.user_id, 120, uow) is True

    def test_improvement_only_returns_false_same_as_best(self):
        p = _policy(repeat_mode="improvement_only")
        uow = _make_uow(policy=p, audit_order_result=(100,))
        assert self.calc.passes_repeat_check(p, self.user_id, 100, uow) is False

    def test_improvement_only_returns_false_worse_than_best(self):
        p = _policy(repeat_mode="improvement_only")
        uow = _make_uow(policy=p, audit_order_result=(100,))
        assert self.calc.passes_repeat_check(p, self.user_id, 80, uow) is False

    def test_improvement_only_prev_best_zero_treated_as_no_history(self):
        """If stored max is 0, any positive award beats it."""
        p = _policy(repeat_mode="improvement_only")
        uow = _make_uow(policy=p, audit_order_result=(0,))
        assert self.calc.passes_repeat_check(p, self.user_id, 1, uow) is True


# ---------------------------------------------------------------------------
# award_for_activity (trainer / daily_test path)
# ---------------------------------------------------------------------------


class TestAwardForActivity:
    calc = PointsCalculatorService()
    user_id = uuid4()

    def _uow_with_policy(self, policy, *, idempotency_hit=False, repeat_blocks=False):
        """Build a UoW whose session mocks chain correctly for award_for_activity."""
        uow = MagicMock()
        uow.points_policies = MagicMock()
        uow.points_policies.get_by_activity_type.return_value = policy
        uow.user_points = MagicMock()

        session = MagicMock()

        # Two queries happen inside award_for_activity:
        # 1. Idempotency check: .filter(source_id=...).first()
        # 2. Repeat check: .filter(source_type=..., user_id=...).first()
        # Both are .query(...).filter(...).first() chains.
        chain1 = MagicMock()
        chain1.filter.return_value.first.return_value = (1,) if idempotency_hit else None

        chain2 = MagicMock()
        # For first_only / improvement_only
        chain2.filter.return_value.first.return_value = (1,) if repeat_blocks else None
        chain2.filter.return_value.order_by.return_value.first.return_value = (
            (999,) if repeat_blocks else None
        )

        session.query.side_effect = [chain1, chain2]
        uow.session = session
        return uow

    def test_policy_not_found_returns_zero(self):
        uow = _make_uow(policy=None)
        result = self.calc.award_for_activity(
            uow, self.user_id, "trainer", score=8, total_questions=10, source_id="1"
        )
        assert result == 0
        uow.user_points.add_points.assert_not_called()

    def test_policy_disabled_returns_zero(self):
        p = _policy(is_enabled=False, mode="fixed", fixed_points=10)
        uow = _make_uow(policy=p)
        result = self.calc.award_for_activity(
            uow, self.user_id, "trainer", score=8, total_questions=10, source_id="1"
        )
        assert result == 0
        uow.user_points.add_points.assert_not_called()

    def test_idempotency_already_awarded_returns_zero(self):
        """Same source_id must never be awarded twice."""
        p = _policy(mode="fixed", fixed_points=10)
        uow = self._uow_with_policy(p, idempotency_hit=True)
        result = self.calc.award_for_activity(
            uow, self.user_id, "trainer", score=8, total_questions=10, source_id="42"
        )
        assert result == 0
        uow.user_points.add_points.assert_not_called()

    def test_below_threshold_returns_zero(self):
        p = _policy(mode="fixed", fixed_points=10, min_score_percent=80)
        uow = self._uow_with_policy(p)
        # 3/10 = 30% < 80%
        result = self.calc.award_for_activity(
            uow, self.user_id, "trainer", score=3, total_questions=10, source_id="1"
        )
        assert result == 0
        uow.user_points.add_points.assert_not_called()

    def test_happy_path_fixed_awards_correct_amount(self):
        p = _policy(mode="fixed", fixed_points=5)
        uow = self._uow_with_policy(p)
        result = self.calc.award_for_activity(
            uow, self.user_id, "trainer", score=8, total_questions=10, source_id="1"
        )
        assert result == 5
        uow.user_points.add_points.assert_called_once()
        call_args = uow.user_points.add_points.call_args
        assert call_args[0][1] == 5  # second positional arg = points

    def test_happy_path_score_based_awards_correct_amount(self):
        p = _policy(mode="score_based", score_multiplier=1.0)
        uow = self._uow_with_policy(p)
        result = self.calc.award_for_activity(
            uow, self.user_id, "daily_test", score=7, total_questions=10, source_id="99"
        )
        assert result == 7
        uow.user_points.add_points.assert_called_once()

    def test_source_id_passed_to_add_points(self):
        """source_id must be forwarded so audit log can detect duplicates."""
        p = _policy(mode="fixed", fixed_points=5)
        uow = self._uow_with_policy(p)
        self.calc.award_for_activity(
            uow, self.user_id, "trainer", score=8, total_questions=10, source_id="session-777"
        )
        call_kwargs = uow.user_points.add_points.call_args[1]
        assert call_kwargs.get("source_id") == "session-777"

    def test_no_points_when_calculated_amount_is_zero(self):
        p = _policy(mode="fixed", fixed_points=0)
        uow = self._uow_with_policy(p)
        result = self.calc.award_for_activity(
            uow, self.user_id, "trainer", score=10, total_questions=10, source_id="1"
        )
        assert result == 0
        uow.user_points.add_points.assert_not_called()


# ---------------------------------------------------------------------------
# Edge cases — policy field validation contract
# ---------------------------------------------------------------------------


class TestEdgeCases:
    calc = PointsCalculatorService()

    def test_ent_full_uses_ent_attempt_audit_source_type(self):
        """ent_full policy → audit log source_type must be 'ent_attempt'
        for backward compat with existing rows."""
        from quiz.services.points_calculator import _AUDIT_SOURCE_TYPE

        assert _AUDIT_SOURCE_TYPE["ent_full"] == "ent_attempt"

    def test_trainer_uses_trainer_audit_source_type(self):
        from quiz.services.points_calculator import _AUDIT_SOURCE_TYPE

        assert _AUDIT_SOURCE_TYPE["trainer"] == "trainer"

    def test_daily_test_uses_daily_test_audit_source_type(self):
        from quiz.services.points_calculator import _AUDIT_SOURCE_TYPE

        assert _AUDIT_SOURCE_TYPE["daily_test"] == "daily_test"
