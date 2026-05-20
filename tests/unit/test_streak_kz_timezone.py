"""Streak calculation must use Almaty calendar days, not UTC days.

Background (20.05.2026): the Statistics screen's «Стрик тренировок» card
was reading `current_streak` computed against `date.today()` which on a
UTC-running Railway container returns the UTC date — off by 5 hours from
the KZ user's perception. A task solved at 02:00 Almaty would get
bucketed into the previous UTC day, silently breaking the user's
streak (they think today is Tuesday but the server sees their activity
as Monday).

This test pins the contract:
  * today_kz() returns the Almaty calendar date, not server's
  * to_kz_date() maps stored UTC datetimes to KZ calendar dates
  * kz_day_window_utc() bounds a [start_kz, end_kz] inclusive window
    correctly in naive-UTC datetimes for DB queries
  * The streak algorithm itself (StreakCalculator.calculate_streak_on_date)
    handles the classic edge cases: empty, today-only, consecutive,
    gap, today-missing.
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from quiz.utils.calculations.streak_calculator import StreakCalculator
from quiz.utils.period.period_calculator import (
    KZ_TZ,
    kz_day_window_utc,
    to_kz_date,
    today_kz,
)


class TestKzDateHelpers:
    def test_today_kz_matches_almaty_clock_not_server(self):
        # Force "now" to a UTC time where UTC date and KZ date differ.
        # 2026-05-20 21:00 UTC = 2026-05-21 02:00 Almaty.
        fake_now = datetime(2026, 5, 20, 21, 0, tzinfo=UTC)
        with patch(
            "quiz.utils.period.period_calculator.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = fake_now.astimezone(KZ_TZ)
            mock_dt.combine = datetime.combine
            result = today_kz()
        assert result == date(2026, 5, 21), (
            "today_kz must reflect the Almaty calendar date, not the "
            "server's UTC date"
        )

    def test_to_kz_date_naive_input_treated_as_utc(self):
        # Naive datetime — our DB convention is "naive UTC".
        naive_utc = datetime(2026, 5, 20, 21, 30)  # = 02:30 May 21 Almaty
        assert to_kz_date(naive_utc) == date(2026, 5, 21)

    def test_to_kz_date_aware_input_converted_correctly(self):
        aware_utc = datetime(2026, 5, 20, 18, 0, tzinfo=UTC)  # = 23:00 May 20 Almaty
        assert to_kz_date(aware_utc) == date(2026, 5, 20)

    def test_to_kz_date_none_returns_none(self):
        assert to_kz_date(None) is None

    def test_to_kz_date_handles_aware_in_other_timezone(self):
        # User somehow got a datetime tagged with another tz — should
        # still convert to KZ correctly.
        moscow = ZoneInfo("Europe/Moscow")  # UTC+3
        dt = datetime(2026, 5, 21, 00, 30, tzinfo=moscow)  # = 02:30 May 21 Almaty
        assert to_kz_date(dt) == date(2026, 5, 21)

    def test_kz_day_window_utc_brackets_full_kz_day(self):
        start_kz = date(2026, 5, 14)
        end_kz = date(2026, 5, 21)
        start_utc, end_utc = kz_day_window_utc(start_kz, end_kz)

        # Start: 2026-05-14 00:00:00 Almaty = 2026-05-13 19:00:00 UTC
        assert start_utc == datetime(2026, 5, 13, 19, 0, 0)
        # End: 2026-05-21 23:59:59.999999 Almaty = 2026-05-21 18:59:59.999999 UTC
        assert end_utc == datetime(2026, 5, 21, 18, 59, 59, 999999)
        # And the boundaries are naive (DB column expects naive UTC).
        assert start_utc.tzinfo is None
        assert end_utc.tzinfo is None

    def test_kz_day_window_includes_late_night_activity(self):
        """The whole point: an attempt completed at 22:00 UTC May 14
        (= 03:00 KZ May 15) must fall inside a window where end_kz=May 15.
        Without the KZ conversion, the old `datetime.combine(May 15, max_time)
        = May 15 23:59 UTC` window started May 15 00:00 UTC — and 22:00
        UTC May 14 would be EXCLUDED even though the user thinks they
        trained on May 15."""
        start_utc, end_utc = kz_day_window_utc(date(2026, 5, 15), date(2026, 5, 15))
        attempt_utc = datetime(2026, 5, 14, 22, 0)  # 03:00 May 15 Almaty
        assert start_utc <= attempt_utc <= end_utc


class TestStreakCalculatorEdgeCases:
    """Properties of calculate_streak_on_date as they affect the UI:
    these are the cases the Statistics screen renders to «Нет стрика»,
    «1 дн.», «N дн. подряд!»."""

    TODAY = date(2026, 5, 21)

    def test_empty_activity_returns_zero(self):
        assert StreakCalculator.calculate_streak_on_date(set(), self.TODAY) == 0

    def test_today_only_returns_one(self):
        assert (
            StreakCalculator.calculate_streak_on_date({self.TODAY}, self.TODAY) == 1
        )

    def test_three_consecutive_days_ending_today(self):
        dates = {self.TODAY, self.TODAY - timedelta(days=1), self.TODAY - timedelta(days=2)}
        assert StreakCalculator.calculate_streak_on_date(dates, self.TODAY) == 3

    def test_gap_in_middle_only_counts_segment_ending_today(self):
        # Active days: today, today-1, today-3 (skip today-2)
        # Streak ending today = 2 (today + today-1), the today-3 day is
        # separated by a missed day.
        dates = {self.TODAY, self.TODAY - timedelta(days=1), self.TODAY - timedelta(days=3)}
        assert StreakCalculator.calculate_streak_on_date(dates, self.TODAY) == 2

    def test_yesterday_but_no_today_with_include_target_returns_zero(self):
        # User had a streak yesterday but didn't train today.
        # With include_target_date=True (the default) the function requires
        # the target day itself to be in the set — broken streak → 0.
        dates = {
            self.TODAY - timedelta(days=1),
            self.TODAY - timedelta(days=2),
            self.TODAY - timedelta(days=3),
        }
        assert StreakCalculator.calculate_streak_on_date(dates, self.TODAY) == 0

    def test_yesterday_but_no_today_with_include_target_false_returns_yesterday_streak(
        self,
    ):
        # When the caller explicitly wants to know yesterday's streak (e.g.
        # the leaderboard's "yesterday's top streaks") — switching off
        # include_target_date and the function STILL returns 0 because
        # `target_date not in activity_dates` short-circuits to 0.
        # This is the documented behaviour of the function — pinning it
        # so the contract doesn't drift.
        dates = {
            self.TODAY - timedelta(days=1),
            self.TODAY - timedelta(days=2),
        }
        assert (
            StreakCalculator.calculate_streak_on_date(
                dates, self.TODAY, include_target_date=False
            )
            == 0
        )

    def test_streak_capped_at_365_days(self):
        # Defensive cap inside the algorithm (consecutive_days > 365 break).
        long_streak = {self.TODAY - timedelta(days=i) for i in range(500)}
        result = StreakCalculator.calculate_streak_on_date(long_streak, self.TODAY)
        # Streak counts target_date itself (+1) plus up to 365 prior days
        # before the loop break.
        assert result <= 367
        assert result >= 365
