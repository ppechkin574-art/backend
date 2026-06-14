"""Unit tests for pure-logic quiz utility classes.

Covers:
- MathUtils.calculate_accuracy
- StreakCalculator.calculate_streak_on_date
- StreakCalculator.calculate_max_streak_in_period
- StreakCalculator.calculate_streak_period
- StreakCalculator.get_activity_level
- AnswerCalculator.calculate_correctness (single_choice / multiple_choice / unknown)
- to_kz_date  (UTC datetime → KZ calendar date)
- kz_day_window_utc (KZ date → UTC bracket)
- PeriodCalculator._get_last_day_of_month
- PeriodCalculator.get_period_days
- PeriodCalculator._parse_month_year

All tests are pure — no DB, no network, no mocks required.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from quiz.utils.calculations.init import AnswerCalculator, MathUtils, StreakCalculator
from quiz.utils.period.init import PeriodCalculator, kz_day_window_utc, to_kz_date


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dates(*iso: str) -> set[date]:
    return {date.fromisoformat(d) for d in iso}


def _consecutive(start: str, n: int) -> set[date]:
    d = date.fromisoformat(start)
    return {d + timedelta(days=i) for i in range(n)}


# ---------------------------------------------------------------------------
# MathUtils.calculate_accuracy
# ---------------------------------------------------------------------------


class TestMathUtilsAccuracy:
    def test_perfect_accuracy(self):
        assert MathUtils.calculate_accuracy(10, 10) == 1.0

    def test_zero_accuracy(self):
        assert MathUtils.calculate_accuracy(0, 10) == 0.0

    def test_partial_accuracy(self):
        assert MathUtils.calculate_accuracy(3, 4) == 0.75

    def test_zero_total_returns_zero(self):
        assert MathUtils.calculate_accuracy(0, 0) == 0.0

    def test_zero_total_no_divzero(self):
        assert MathUtils.calculate_accuracy(5, 0) == 0.0

    def test_fractional_result(self):
        result = MathUtils.calculate_accuracy(1, 3)
        assert abs(result - 1 / 3) < 1e-9


# ---------------------------------------------------------------------------
# StreakCalculator.calculate_streak_on_date
# ---------------------------------------------------------------------------


class TestStreakOnDate:
    def test_empty_set_returns_0(self):
        assert StreakCalculator.calculate_streak_on_date(set(), date(2026, 1, 1)) == 0

    def test_target_date_not_in_set_returns_0(self):
        dates = _dates("2026-01-01", "2026-01-02")
        assert StreakCalculator.calculate_streak_on_date(dates, date(2026, 1, 3)) == 0

    def test_single_day_streak_1(self):
        dates = _dates("2026-01-01")
        assert StreakCalculator.calculate_streak_on_date(dates, date(2026, 1, 1)) == 1

    def test_three_consecutive_streak_3(self):
        dates = _dates("2026-01-01", "2026-01-02", "2026-01-03")
        assert StreakCalculator.calculate_streak_on_date(dates, date(2026, 1, 3)) == 3

    def test_gap_before_target_streak_1(self):
        dates = _dates("2026-01-01", "2026-01-02", "2026-01-05")
        assert StreakCalculator.calculate_streak_on_date(dates, date(2026, 1, 5)) == 1

    def test_include_target_date_false_and_missing_returns_0(self):
        dates = _dates("2026-01-01", "2026-01-02")
        result = StreakCalculator.calculate_streak_on_date(
            dates, date(2026, 1, 3), include_target_date=False
        )
        assert result == 0

    def test_future_dates_ignored(self):
        dates = _dates("2026-01-01", "2026-01-02", "2026-01-03", "2026-01-10")
        assert StreakCalculator.calculate_streak_on_date(dates, date(2026, 1, 3)) == 3

    def test_long_streak_counted(self):
        dates = _consecutive("2026-01-01", 30)
        assert StreakCalculator.calculate_streak_on_date(dates, date(2026, 1, 30)) == 30


# ---------------------------------------------------------------------------
# StreakCalculator.calculate_max_streak_in_period
# ---------------------------------------------------------------------------


class TestMaxStreakInPeriod:
    def test_empty_set_returns_0(self):
        assert StreakCalculator.calculate_max_streak_in_period(set(), date(2026, 1, 1), date(2026, 1, 7)) == 0

    def test_all_consecutive_in_period(self):
        dates = _consecutive("2026-01-01", 7)
        assert StreakCalculator.calculate_max_streak_in_period(dates, date(2026, 1, 1), date(2026, 1, 7)) == 7

    def test_gap_splits_streak(self):
        dates = _dates("2026-01-01", "2026-01-02", "2026-01-03",
                       "2026-01-05", "2026-01-06")
        result = StreakCalculator.calculate_max_streak_in_period(
            dates, date(2026, 1, 1), date(2026, 1, 7)
        )
        assert result == 3  # days 1-2-3

    def test_dates_outside_period_excluded(self):
        # long run before and after period
        dates = _consecutive("2025-12-25", 5) | _dates("2026-01-05", "2026-01-06")
        result = StreakCalculator.calculate_max_streak_in_period(
            dates, date(2026, 1, 1), date(2026, 1, 7)
        )
        assert result == 2  # only jan 5-6 inside period

    def test_single_day_streak_1(self):
        dates = _dates("2026-01-03")
        assert StreakCalculator.calculate_max_streak_in_period(
            dates, date(2026, 1, 1), date(2026, 1, 7)
        ) == 1

    def test_two_equal_runs_returns_max(self):
        dates = _dates("2026-01-01", "2026-01-02", "2026-01-04", "2026-01-05")
        result = StreakCalculator.calculate_max_streak_in_period(
            dates, date(2026, 1, 1), date(2026, 1, 7)
        )
        assert result == 2


# ---------------------------------------------------------------------------
# StreakCalculator.calculate_streak_period
# ---------------------------------------------------------------------------


class TestStreakPeriod:
    def test_empty_set_streak_0_and_all_false(self):
        streak, history = StreakCalculator.calculate_streak_period(
            set(), date(2026, 1, 1), date(2026, 1, 3)
        )
        assert streak == 0
        assert history == {
            "2026-01-01": False,
            "2026-01-02": False,
            "2026-01-03": False,
        }

    def test_all_days_present(self):
        dates = _dates("2026-01-01", "2026-01-02", "2026-01-03")
        streak, history = StreakCalculator.calculate_streak_period(
            dates, date(2026, 1, 1), date(2026, 1, 3)
        )
        assert streak == 3
        assert all(history.values())

    def test_history_has_entry_for_every_day(self):
        dates = _dates("2026-01-03")
        _, history = StreakCalculator.calculate_streak_period(
            dates, date(2026, 1, 1), date(2026, 1, 5)
        )
        assert set(history.keys()) == {
            "2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"
        }

    def test_partial_presence_history(self):
        dates = _dates("2026-01-01", "2026-01-03")
        _, history = StreakCalculator.calculate_streak_period(
            dates, date(2026, 1, 1), date(2026, 1, 3)
        )
        assert history["2026-01-01"] is True
        assert history["2026-01-02"] is False
        assert history["2026-01-03"] is True

    def test_dates_outside_period_excluded_from_history(self):
        dates = _dates("2025-12-31", "2026-01-01", "2026-01-02")
        _, history = StreakCalculator.calculate_streak_period(
            dates, date(2026, 1, 1), date(2026, 1, 2)
        )
        assert "2025-12-31" not in history


# ---------------------------------------------------------------------------
# StreakCalculator.get_activity_level
# ---------------------------------------------------------------------------


class TestActivityLevel:
    def test_very_high_above_2_per_day(self):
        assert StreakCalculator.get_activity_level(14, 7) == "very_high"

    def test_high_at_exactly_1_per_day(self):
        assert StreakCalculator.get_activity_level(7, 7) == "high"

    def test_medium_at_0_3_per_day(self):
        assert StreakCalculator.get_activity_level(3, 10) == "medium"  # 0.3/day

    def test_low_below_0_3_per_day(self):
        assert StreakCalculator.get_activity_level(1, 10) == "low"  # 0.1/day

    def test_zero_attempts_low(self):
        assert StreakCalculator.get_activity_level(0, 7) == "low"

    def test_zero_period_returns_low(self):
        assert StreakCalculator.get_activity_level(100, 0) == "low"

    def test_boundary_exactly_2_very_high(self):
        assert StreakCalculator.get_activity_level(2, 1) == "very_high"

    def test_boundary_below_2_high(self):
        assert StreakCalculator.get_activity_level(1, 1) == "high"


# ---------------------------------------------------------------------------
# AnswerCalculator.calculate_correctness
# ---------------------------------------------------------------------------


class TestAnswerCalculatorSingleChoice:
    def test_correct_single_choice(self):
        is_correct, details = AnswerCalculator.calculate_correctness(
            "single_choice", chosen_variant_ids={1}, correct_variant_ids={1}
        )
        assert is_correct is True
        assert details["type"] == "single_choice"

    def test_wrong_single_choice(self):
        is_correct, _ = AnswerCalculator.calculate_correctness(
            "single_choice", chosen_variant_ids={2}, correct_variant_ids={1}
        )
        assert is_correct is False

    def test_empty_chosen_single_choice(self):
        is_correct, _ = AnswerCalculator.calculate_correctness(
            "single_choice", chosen_variant_ids=set(), correct_variant_ids={1}
        )
        assert is_correct is False

    def test_multiple_ids_chosen_for_single_still_correct_if_one_matches(self):
        is_correct, _ = AnswerCalculator.calculate_correctness(
            "single_choice", chosen_variant_ids={1, 2}, correct_variant_ids={1}
        )
        assert is_correct is True


class TestAnswerCalculatorMultipleChoice:
    def test_perfect_multiple_choice(self):
        is_correct, details = AnswerCalculator.calculate_correctness(
            "multiple_choice", chosen_variant_ids={1, 2}, correct_variant_ids={1, 2}
        )
        assert is_correct is True
        assert details["correct_selected"] == 2
        assert details["incorrect_selected"] == 0
        assert details["correct_weight"] == 1.0

    def test_one_incorrect_selected_fails(self):
        is_correct, details = AnswerCalculator.calculate_correctness(
            "multiple_choice", chosen_variant_ids={1, 3}, correct_variant_ids={1, 2}
        )
        assert is_correct is False
        assert details["incorrect_selected"] == 1

    def test_missing_one_correct_fails(self):
        is_correct, details = AnswerCalculator.calculate_correctness(
            "multiple_choice", chosen_variant_ids={1}, correct_variant_ids={1, 2}
        )
        assert is_correct is False
        assert details["correct_selected"] == 1

    def test_empty_chosen_fails(self):
        is_correct, _ = AnswerCalculator.calculate_correctness(
            "multiple_choice", chosen_variant_ids=set(), correct_variant_ids={1, 2}
        )
        assert is_correct is False

    def test_no_correct_variants_returns_false(self):
        is_correct, details = AnswerCalculator.calculate_correctness(
            "multiple_choice", chosen_variant_ids={1}, correct_variant_ids=set()
        )
        assert is_correct is False
        assert "error" in details

    def test_partial_credit_weight(self):
        _, details = AnswerCalculator.calculate_correctness(
            "multiple_choice", chosen_variant_ids={1}, correct_variant_ids={1, 2}
        )
        assert details["correct_weight"] == 0.5  # 1 of 2 correct selected

    def test_three_of_three_correct(self):
        is_correct, details = AnswerCalculator.calculate_correctness(
            "multiple_choice", chosen_variant_ids={1, 2, 3}, correct_variant_ids={1, 2, 3}
        )
        assert is_correct is True
        assert details["correct_weight"] == 1.0


class TestAnswerCalculatorUnknownType:
    def test_unknown_type_returns_false(self):
        is_correct, details = AnswerCalculator.calculate_correctness(
            "essay", chosen_variant_ids={1}, correct_variant_ids={1}
        )
        assert is_correct is False
        assert details["type"] == "unknown"


# ---------------------------------------------------------------------------
# to_kz_date
# ---------------------------------------------------------------------------


class TestToKzDate:
    def test_none_returns_none(self):
        assert to_kz_date(None) is None

    def test_utc_midnight_stays_same_date(self):
        dt = datetime(2026, 6, 13, 0, 0, 0, tzinfo=UTC)
        # KZ (Asia/Almaty) is UTC+5, so 00:00 UTC = 05:00 KZ — still same KZ date
        result = to_kz_date(dt)
        assert result == date(2026, 6, 13)

    def test_utc_2200_converts_to_next_kz_date(self):
        # 22:00 UTC = 03:00 KZ next day
        dt = datetime(2026, 6, 13, 22, 0, 0, tzinfo=UTC)
        result = to_kz_date(dt)
        assert result == date(2026, 6, 14)

    def test_naive_datetime_treated_as_utc(self):
        dt = datetime(2026, 6, 13, 12, 0, 0)  # naive
        result = to_kz_date(dt)
        assert result == date(2026, 6, 13)

    def test_utc_1900_same_kz_date(self):
        # 19:00 UTC = 00:00 KZ on next day? No: 19+5=24 = midnight KZ
        # actually 19:00 UTC = 00:00 KZ next day (midnight), but .date() is still next day?
        # 2026-06-13 19:00 UTC → 2026-06-14 00:00 KZ → date is 2026-06-14
        dt = datetime(2026, 6, 13, 19, 0, 0, tzinfo=UTC)
        result = to_kz_date(dt)
        assert result == date(2026, 6, 14)

    def test_utc_1859_same_kz_date(self):
        # 18:59 UTC = 23:59 KZ → same KZ date
        dt = datetime(2026, 6, 13, 18, 59, 0, tzinfo=UTC)
        result = to_kz_date(dt)
        assert result == date(2026, 6, 13)


# ---------------------------------------------------------------------------
# kz_day_window_utc
# ---------------------------------------------------------------------------


class TestKzDayWindowUtc:
    def test_start_is_before_end(self):
        start, end = kz_day_window_utc(date(2026, 6, 13), date(2026, 6, 13))
        assert start < end

    def test_single_day_window_spans_24h(self):
        start, end = kz_day_window_utc(date(2026, 6, 13), date(2026, 6, 13))
        delta = end - start
        assert abs(delta.total_seconds() - 86399.999999) < 1  # ~24h

    def test_result_is_naive_utc(self):
        start, end = kz_day_window_utc(date(2026, 6, 13), date(2026, 6, 14))
        assert start.tzinfo is None
        assert end.tzinfo is None

    def test_kz_midnight_is_utc_minus5(self):
        # KZ UTC+5: midnight KZ = 19:00 UTC previous day (UTC-5h)
        start, _ = kz_day_window_utc(date(2026, 6, 13), date(2026, 6, 13))
        # start = 2026-06-13 00:00 KZ = 2026-06-12 19:00 UTC
        assert start.year == 2026
        assert start.month == 6
        assert start.day == 12
        assert start.hour == 19

    def test_multi_day_window_end_after_start(self):
        start, end = kz_day_window_utc(date(2026, 6, 10), date(2026, 6, 14))
        assert (end - start).days == 4

    def test_reversed_order_start_before_end(self):
        # The function takes start_kz, end_kz; end > start so window is valid
        start, end = kz_day_window_utc(date(2026, 6, 1), date(2026, 6, 30))
        assert start < end


# ---------------------------------------------------------------------------
# PeriodCalculator._get_last_day_of_month
# ---------------------------------------------------------------------------


class TestGetLastDayOfMonth:
    def test_january_31(self):
        assert PeriodCalculator._get_last_day_of_month(2026, 1) == date(2026, 1, 31)

    def test_february_non_leap_28(self):
        assert PeriodCalculator._get_last_day_of_month(2025, 2) == date(2025, 2, 28)

    def test_february_leap_29(self):
        assert PeriodCalculator._get_last_day_of_month(2024, 2) == date(2024, 2, 29)

    def test_april_30(self):
        assert PeriodCalculator._get_last_day_of_month(2026, 4) == date(2026, 4, 30)

    def test_december_31(self):
        assert PeriodCalculator._get_last_day_of_month(2026, 12) == date(2026, 12, 31)

    def test_november_30(self):
        assert PeriodCalculator._get_last_day_of_month(2026, 11) == date(2026, 11, 30)


# ---------------------------------------------------------------------------
# PeriodCalculator.get_period_days
# ---------------------------------------------------------------------------


class TestGetPeriodDays:
    def test_same_day_is_1(self):
        d = date(2026, 1, 1)
        assert PeriodCalculator.get_period_days(d, d) == 1

    def test_7_days(self):
        assert PeriodCalculator.get_period_days(date(2026, 1, 1), date(2026, 1, 7)) == 7

    def test_30_days(self):
        assert PeriodCalculator.get_period_days(date(2026, 1, 1), date(2026, 1, 30)) == 30

    def test_across_month_boundary(self):
        assert PeriodCalculator.get_period_days(date(2026, 1, 28), date(2026, 2, 3)) == 7


# ---------------------------------------------------------------------------
# PeriodCalculator._parse_month_year
# ---------------------------------------------------------------------------


class TestParseMonthYear:
    def test_none_returns_current_year_month(self):
        from quiz.utils.period.init import today_kz
        today = today_kz()
        year, month = PeriodCalculator._parse_month_year(None)
        assert year == today.year
        assert month == today.month

    def test_year_month_format(self):
        year, month = PeriodCalculator._parse_month_year("2026-6")
        assert year == 2026
        assert month == 6

    def test_month_only_uses_current_year(self):
        from quiz.utils.period.init import today_kz
        today = today_kz()
        year, month = PeriodCalculator._parse_month_year("3")
        assert year == today.year
        assert month == 3

    def test_invalid_format_raises(self):
        with pytest.raises((ValueError, Exception)):
            PeriodCalculator._parse_month_year("2026-6-1")
