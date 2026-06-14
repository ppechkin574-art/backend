"""Unit tests for AttendanceService.

Covers the pure-logic methods that can be tested without DB:
- _calculate_streak_from_dates: all edge cases for current/longest streak,
  cycle arithmetic, total points calculation
- _get_calendar_for_month: month filtering, streak_day assignment,
  cycle_day and multiplier calculation
- _get_date_only: datetime → date
- CYCLE_LENGTH / BASE_POINTS constants contract

AttendanceService._get_user_activity_dates and get_attendance_info require a
DB session and are integration-tested via conftest smoke tests. The logic
branching inside them all flows through _calculate_streak_from_dates which is
fully covered here.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

# Register ORM models to resolve SQLAlchemy mapper relationships.
import quiz.models  # noqa: F401
import student.models  # noqa: F401

from quiz.services.attendance import AttendanceService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service() -> AttendanceService:
    uow = MagicMock()
    cache = MagicMock()
    return AttendanceService(uow=uow, cache_service=cache)


def _dates(*args) -> list[date]:
    """Build a sorted date list from ISO strings or date objects."""
    out = []
    for a in args:
        out.append(date.fromisoformat(a) if isinstance(a, str) else a)
    return sorted(out)


def _consecutive(start: str, n: int) -> list[date]:
    """n consecutive dates starting from start (ISO string)."""
    d = date.fromisoformat(start)
    return [d + timedelta(days=i) for i in range(n)]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_cycle_length_is_5():
    svc = _make_service()
    assert svc.CYCLE_LENGTH == 5


def test_base_points_is_1():
    svc = _make_service()
    assert svc.BASE_POINTS == 1


# ---------------------------------------------------------------------------
# _calculate_streak_from_dates — empty / single / basic
# ---------------------------------------------------------------------------


class TestCalculateStreakEmpty:
    def test_empty_dates_returns_zeros(self):
        svc = _make_service()
        r = svc._calculate_streak_from_dates([])
        assert r["current_days"] == 0
        assert r["longest_days"] == 0
        assert r["total_points"] == 0
        assert r["current_cycle_day"] == 0
        assert r["completed_cycles"] == 0
        assert r["cycle_number"] == 1

    def test_single_date_current_1(self):
        svc = _make_service()
        r = svc._calculate_streak_from_dates(_dates("2026-01-01"))
        assert r["current_days"] == 1
        assert r["longest_days"] == 1


class TestCalculateStreakBasic:
    def test_two_consecutive_current_2(self):
        svc = _make_service()
        r = svc._calculate_streak_from_dates(_dates("2026-01-01", "2026-01-02"))
        assert r["current_days"] == 2
        assert r["longest_days"] == 2

    def test_gap_resets_current(self):
        svc = _make_service()
        # old streak of 3, gap, new streak of 2
        d = _dates("2026-01-01", "2026-01-02", "2026-01-03",
                   "2026-01-05", "2026-01-06")
        r = svc._calculate_streak_from_dates(d)
        assert r["current_days"] == 2
        assert r["longest_days"] == 3

    def test_single_day_gap_breaks_streak(self):
        svc = _make_service()
        d = _dates("2026-01-01", "2026-01-03")  # missing 2026-01-02
        r = svc._calculate_streak_from_dates(d)
        assert r["current_days"] == 1
        assert r["longest_days"] == 1

    def test_longest_streak_when_current_shorter(self):
        svc = _make_service()
        d = _consecutive("2026-01-01", 7) + _dates("2026-01-10")  # gap then 1 day
        r = svc._calculate_streak_from_dates(d)
        assert r["current_days"] == 1
        assert r["longest_days"] == 7


# ---------------------------------------------------------------------------
# cycle arithmetic
# ---------------------------------------------------------------------------


class TestCycleArithmetic:
    def test_5_days_completes_cycle_1(self):
        svc = _make_service()
        d = _consecutive("2026-01-01", 5)
        r = svc._calculate_streak_from_dates(d)
        # (5-1)//5 = 0 completed cycles; cycle_number = 0+1 = 1; day 5 is the last day of cycle 1
        assert r["completed_cycles"] == 0
        assert r["current_cycle_day"] == 5
        assert r["cycle_number"] == 1

    def test_cycle_day_resets_after_full_cycle(self):
        svc = _make_service()
        d = _consecutive("2026-01-01", 6)  # 1 full cycle + day 1 of next
        r = svc._calculate_streak_from_dates(d)
        assert r["current_cycle_day"] == 1
        assert r["completed_cycles"] == 1

    def test_exactly_10_days_two_complete_cycles(self):
        svc = _make_service()
        d = _consecutive("2026-01-01", 10)
        r = svc._calculate_streak_from_dates(d)
        # (10-1)//5 = 1 completed cycle; cycle_number = 1+1 = 2; day 10 is last day of cycle 2
        assert r["completed_cycles"] == 1
        assert r["current_cycle_day"] == 5
        assert r["cycle_number"] == 2

    def test_current_cycle_day_1_on_day_11(self):
        svc = _make_service()
        d = _consecutive("2026-01-01", 11)
        r = svc._calculate_streak_from_dates(d)
        assert r["current_cycle_day"] == 1

    def test_no_cycles_completed_for_4_days(self):
        svc = _make_service()
        d = _consecutive("2026-01-01", 4)
        r = svc._calculate_streak_from_dates(d)
        assert r["completed_cycles"] == 0
        assert r["cycle_number"] == 1


# ---------------------------------------------------------------------------
# total_points accumulation
# ---------------------------------------------------------------------------


class TestTotalPoints:
    def test_1_day_earns_1_point(self):
        svc = _make_service()
        r = svc._calculate_streak_from_dates(_dates("2026-01-01"))
        assert r["total_points"] == 1

    def test_5_days_cycle_1_earns_5_points(self):
        svc = _make_service()
        d = _consecutive("2026-01-01", 5)
        r = svc._calculate_streak_from_dates(d)
        # Days 1-5 in cycle 1 → 1 point each → 5 total
        assert r["total_points"] == 5

    def test_6th_day_earns_2_points(self):
        svc = _make_service()
        d = _consecutive("2026-01-01", 6)
        r = svc._calculate_streak_from_dates(d)
        # Days 1-5: 5 points + day 6 (cycle 2): 2 points = 7
        assert r["total_points"] == 7

    def test_10_days_cycle_2_all_days_2x(self):
        svc = _make_service()
        d = _consecutive("2026-01-01", 10)
        r = svc._calculate_streak_from_dates(d)
        # Days 1-5: 5×1=5, days 6-10: 5×2=10 → total=15
        assert r["total_points"] == 15

    def test_broken_streak_accumulates_both_parts(self):
        svc = _make_service()
        # streak of 3 (3 points) + gap + streak of 2 (2 points) = 5
        d = _dates("2026-01-01", "2026-01-02", "2026-01-03",
                   "2026-01-05", "2026-01-06")
        r = svc._calculate_streak_from_dates(d)
        assert r["total_points"] == 5


# ---------------------------------------------------------------------------
# _get_date_only
# ---------------------------------------------------------------------------


class TestGetDateOnly:
    def test_strips_time_component(self):
        svc = _make_service()
        dt = datetime(2026, 6, 13, 15, 30, 0, tzinfo=UTC)
        assert svc._get_date_only(dt) == date(2026, 6, 13)


# ---------------------------------------------------------------------------
# _get_calendar_for_month
# ---------------------------------------------------------------------------


class TestCalendarForMonth:
    def test_filters_to_requested_month(self):
        svc = _make_service()
        all_dates = _consecutive("2026-01-28", 10)  # spans Jan and Feb
        result = svc._get_calendar_for_month(all_dates, 2026, 2)
        # Only Feb dates should appear
        assert all(d.month == 2 for d in result.attendance_dates)

    def test_empty_month_returns_empty_details(self):
        svc = _make_service()
        all_dates = _consecutive("2026-01-01", 5)
        result = svc._get_calendar_for_month(all_dates, 2026, 3)
        assert result.attendance_dates == []
        assert result.details == []

    def test_year_and_month_in_result(self):
        svc = _make_service()
        result = svc._get_calendar_for_month([], 2026, 6)
        assert result.year == 2026
        assert result.month == 6

    def test_streak_day_assignment_correct(self):
        svc = _make_service()
        all_dates = _consecutive("2026-01-01", 7)  # 7 consecutive days
        result = svc._get_calendar_for_month(all_dates, 2026, 1)
        # streak_day for Jan 1 should be 1, Jan 7 should be 7
        days = {d.date: d.streak_day for d in result.details}
        assert days[date(2026, 1, 1)] == 1
        assert days[date(2026, 1, 7)] == 7

    def test_cycle_day_rolls_over_at_5(self):
        svc = _make_service()
        all_dates = _consecutive("2026-01-01", 10)
        result = svc._get_calendar_for_month(all_dates, 2026, 1)
        days = {d.date: d.cycle_day for d in result.details}
        assert days[date(2026, 1, 5)] == 5
        assert days[date(2026, 1, 6)] == 1  # new cycle starts
        assert days[date(2026, 1, 10)] == 5

    def test_multiplier_increases_each_cycle(self):
        svc = _make_service()
        all_dates = _consecutive("2026-01-01", 10)
        result = svc._get_calendar_for_month(all_dates, 2026, 1)
        days = {d.date: d.multiplier for d in result.details}
        # Cycle 1: days 1-5 multiplier=1; cycle 2: days 6-10 multiplier=2
        assert days[date(2026, 1, 5)] == 1
        assert days[date(2026, 1, 6)] == 2

    def test_points_per_day_is_base_times_multiplier(self):
        svc = _make_service()
        all_dates = _consecutive("2026-01-01", 6)
        result = svc._get_calendar_for_month(all_dates, 2026, 1)
        days = {d.date: d.points for d in result.details}
        # Day 6 is in cycle 2 → points = 1 × 2 = 2
        assert days[date(2026, 1, 6)] == 2

    def test_broken_streak_resets_streak_day(self):
        svc = _make_service()
        # 3 consecutive, gap, 2 consecutive
        all_dates = _dates("2026-01-01", "2026-01-02", "2026-01-03",
                           "2026-01-05", "2026-01-06")
        result = svc._get_calendar_for_month(all_dates, 2026, 1)
        days = {d.date: d.streak_day for d in result.details}
        assert days[date(2026, 1, 3)] == 3
        assert days[date(2026, 1, 5)] == 1  # reset after gap
        assert days[date(2026, 1, 6)] == 2
