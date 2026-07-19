"""Pin the leaderboard-points auto-reset schedule — in particular the
"weekly_monday" mode added for the "Еженедельный спринт" requirement
(CRM task #6: baллы всех участников сбрасываются каждый понедельник в
00:00). A bad offset here silently resets on the wrong day (or the
wrong hour, if the Almaty conversion is skipped) for every user on the
leaderboard, so the boundary conditions are worth locking down.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from leaderboard_points.service import (
    ALMATY_TZ,
    LeaderboardPointsService,
    current_week_start_almaty,
    next_monday_midnight_almaty,
)


def _fake_settings(**overrides):
    base = {
        "auto_reset_enabled": True,
        "reset_mode": "weekly_monday",
        "interval_days": 30,
        "last_reset_at": None,
        "updated_at": datetime.now(UTC),
        "updated_by": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_service(settings):
    repo = MagicMock()
    repo.db = MagicMock()
    repo.get_or_create_settings.return_value = settings
    return LeaderboardPointsService(repo=repo), repo


# ─── next_monday_midnight_almaty ────────────────────────────────────────


class TestNextMondayMidnightAlmaty:
    def test_from_monday_morning_rolls_to_next_monday(self):
        # 2026-07-20 is a Monday. 10:00 Almaty (UTC+5) == 05:00 UTC.
        # Next Monday 00:00 Almaty is 2026-07-27T00:00+05:00 == 2026-07-26T19:00 UTC.
        after = datetime(2026, 7, 20, 5, 0, tzinfo=UTC)
        result = next_monday_midnight_almaty(after)
        assert result == datetime(2026, 7, 26, 19, 0, tzinfo=UTC)

    def test_from_midweek_rolls_to_upcoming_monday(self):
        # 2026-07-19 is a Sunday. Upcoming Monday 00:00 Almaty (UTC+5) is
        # 2026-07-20T00:00+05:00 == 2026-07-19T19:00 UTC.
        after = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
        result = next_monday_midnight_almaty(after)
        assert result == datetime(2026, 7, 19, 19, 0, tzinfo=UTC)

    def test_result_is_always_a_monday_in_almaty(self):
        after = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
        result = next_monday_midnight_almaty(after)
        local = result.astimezone(ALMATY_TZ)
        assert local.weekday() == 0
        assert (local.hour, local.minute, local.second) == (0, 0, 0)

    def test_exactly_at_monday_midnight_rolls_to_next_week_not_same_instant(self):
        # 2026-07-20 00:00 Almaty == 2026-07-19 19:00 UTC.
        after = datetime(2026, 7, 19, 19, 0, tzinfo=UTC)
        result = next_monday_midnight_almaty(after)
        assert result == datetime(2026, 7, 26, 19, 0, tzinfo=UTC)
        assert result > after


# ─── current_week_start_almaty (CRM task #7 — sprint winner) ───────────
#
# Symmetric to next_monday_midnight_almaty above, but "most recent Monday
# 00:00 Asia/Almaty AT-OR-BEFORE `now`" instead of "next Monday strictly
# after". Deliberately independent of reset_mode/last_reset_at — see the
# function's docstring.


class TestCurrentWeekStartAlmaty:
    def test_from_monday_morning_returns_this_mondays_midnight(self):
        # 2026-07-20 is a Monday. 10:00 Almaty (UTC+5) == 05:00 UTC.
        # This Monday 00:00 Almaty is 2026-07-20T00:00+05:00 == 2026-07-19T19:00 UTC.
        after = datetime(2026, 7, 20, 5, 0, tzinfo=UTC)
        result = current_week_start_almaty(after)
        assert result == datetime(2026, 7, 19, 19, 0, tzinfo=UTC)

    def test_exactly_at_monday_midnight_returns_same_instant(self):
        # 2026-07-20 00:00 Almaty == 2026-07-19 19:00 UTC — the boundary
        # instant belongs to the week that just started ("at-or-before"
        # is inclusive), unlike next_monday_midnight_almaty which rolls
        # a same-instant match to the FOLLOWING week.
        after = datetime(2026, 7, 19, 19, 0, tzinfo=UTC)
        result = current_week_start_almaty(after)
        assert result == after

    def test_from_midweek_rolls_back_to_this_mondays_midnight(self):
        # 2026-07-22 is a Wednesday. Noon UTC == 17:00 Almaty (still Wed).
        # This week's Monday 00:00 Almaty is 2026-07-20T00:00+05:00 ==
        # 2026-07-19T19:00 UTC.
        after = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
        result = current_week_start_almaty(after)
        assert result == datetime(2026, 7, 19, 19, 0, tzinfo=UTC)

    def test_from_sunday_night_rolls_back_to_prior_mondays_midnight(self):
        # 2026-07-19 is a Sunday. 18:00 UTC == 23:00 Almaty (still Sun,
        # the week hasn't rolled to the next Monday yet). Most recent
        # Monday 00:00 Almaty is the PRIOR week: 2026-07-13T00:00+05:00
        # == 2026-07-12T19:00 UTC.
        after = datetime(2026, 7, 19, 18, 0, tzinfo=UTC)
        result = current_week_start_almaty(after)
        assert result == datetime(2026, 7, 12, 19, 0, tzinfo=UTC)

    def test_result_is_always_a_monday_in_almaty(self):
        after = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
        result = current_week_start_almaty(after)
        local = result.astimezone(ALMATY_TZ)
        assert local.weekday() == 0
        assert (local.hour, local.minute, local.second) == (0, 0, 0)

    def test_result_is_always_at_or_before_now(self):
        after = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
        result = current_week_start_almaty(after)
        assert result <= after


# ─── reset_all_points_if_due — weekly_monday mode ──────────────────────


class TestResetAllPointsIfDueWeekly:
    def test_first_ever_check_with_no_last_reset_is_due_immediately(self):
        settings = _fake_settings(reset_mode="weekly_monday", last_reset_at=None)
        service, repo = _make_service(settings)
        repo.bulk_reset_all.return_value = 5

        result = service.reset_all_points_if_due()

        assert result.ran is True
        assert result.users_reset == 5
        repo.bulk_reset_all.assert_called_once()

    def test_not_due_before_next_monday(self):
        # last_reset_at = this past Monday morning; "now" is mocked via
        # last_reset_at being recent enough that due_at is in the future.
        settings = _fake_settings(
            reset_mode="weekly_monday",
            last_reset_at=datetime.now(UTC),
        )
        service, repo = _make_service(settings)

        result = service.reset_all_points_if_due()

        assert result.ran is False
        assert result.next_reset_at is not None
        repo.bulk_reset_all.assert_not_called()

    def test_due_after_last_reset_more_than_a_week_ago(self):
        settings = _fake_settings(
            reset_mode="weekly_monday",
            last_reset_at=datetime(2020, 1, 1, tzinfo=UTC),  # long past
        )
        service, repo = _make_service(settings)
        repo.bulk_reset_all.return_value = 3

        result = service.reset_all_points_if_due()

        assert result.ran is True
        assert result.users_reset == 3
        assert "спринт" in repo.bulk_reset_all.call_args[0][0].lower()

    def test_disabled_never_resets_regardless_of_mode(self):
        settings = _fake_settings(
            reset_mode="weekly_monday",
            auto_reset_enabled=False,
            last_reset_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        service, repo = _make_service(settings)

        result = service.reset_all_points_if_due()

        assert result.ran is False
        repo.bulk_reset_all.assert_not_called()


# ─── interval mode is unaffected (regression guard) ────────────────────


class TestResetAllPointsIfDueIntervalRegression:
    def test_interval_mode_still_uses_interval_days(self):
        settings = _fake_settings(
            reset_mode="interval",
            interval_days=30,
            last_reset_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        service, repo = _make_service(settings)
        repo.bulk_reset_all.return_value = 1

        result = service.reset_all_points_if_due()

        assert result.ran is True
        assert "интервал 30" in repo.bulk_reset_all.call_args[0][0]
