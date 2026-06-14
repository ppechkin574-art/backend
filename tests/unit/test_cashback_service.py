"""Unit tests for CashbackService.

Covers the following testable business logic:
- Constants: ASTANA_OFFSET, STREAK_LENGTH, MAX_STREAKS, REWARD_AMOUNT
- _get_utc_range_for_astana_date: returns (start, end) datetimes for a date
- check_and_update: streak state machine
  - first visit (no prior state) → creates state
  - already completed today → idempotent
  - gap in streak → resets streak_number=1, day_in_streak=0
  - progress through streak days
  - completing day 5 (STREAK_LENGTH) → reward earned, cycle advances
  - completing day 5 at MAX_STREAKS → wraps back to streak 1
  - not all conditions met → no progress

All tests mock UoW, cache_service, and bank_service.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import quiz.models  # noqa: F401 — ORM mapper registration
import student.models  # noqa: F401

from quiz.services.cashback import CashbackService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(uow=None, cache=None, bank=None) -> CashbackService:
    if uow is None:
        uow = MagicMock()
        uow.__enter__ = lambda s: s
        uow.__exit__ = MagicMock(return_value=False)
    if cache is None:
        cache = MagicMock()
    if bank is None:
        bank = MagicMock()
    return CashbackService(uow=uow, cache_service=cache, bank_service=bank)


def _fake_state(
    current_streak_number=1,
    current_day_in_streak=0,
    total_streaks_completed=0,
    total_cashback_earned=0,
    last_completed_date=None,
    id=1,
    student_guid=None,
):
    return SimpleNamespace(
        id=id,
        student_guid=student_guid or uuid4(),
        current_streak_number=current_streak_number,
        current_day_in_streak=current_day_in_streak,
        total_streaks_completed=total_streaks_completed,
        total_cashback_earned=total_cashback_earned,
        last_completed_date=last_completed_date,
    )


def _uow_with_state(state=None, existing_today=None, last_completion=None,
                    all_conditions_met=True):
    """Build a UoW mock that drives check_and_update through specified paths."""
    uow = MagicMock()
    uow.__enter__ = lambda s: s
    uow.__exit__ = MagicMock(return_value=False)

    uow.cashback.get_user_state.return_value = state
    uow.cashback.get_daily_completion.return_value = existing_today
    uow.cashback.get_last_completion.return_value = last_completion

    # _check_today_conditions sub-repo calls
    uow.attendance.has_app_open_event.return_value = all_conditions_met
    uow.ent_attempts.count_full_ents_above_threshold.return_value = (
        1 if all_conditions_met else 0
    )
    uow.ent_attempts.count_practice_ents_above_threshold.return_value = (
        2 if all_conditions_met else 0
    )
    uow.daily_tests.count_completed_daily_tests_in_range.return_value = (
        1 if all_conditions_met else 0
    )
    uow.daily_tests.get_subject_preferences.return_value = None  # requires 1 test
    uow.trainer_attempts.count_completed_trainers_above_threshold.return_value = (
        3 if all_conditions_met else 0
    )
    return uow


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_astana_offset_is_5_hours():
    assert CashbackService.ASTANA_OFFSET == timedelta(hours=5)


def test_streak_length_is_5():
    assert CashbackService.STREAK_LENGTH == 5


def test_max_streaks_is_6():
    assert CashbackService.MAX_STREAKS == 6


def test_reward_amount_is_500():
    assert CashbackService.REWARD_AMOUNT == 500


# ---------------------------------------------------------------------------
# _get_utc_range_for_astana_date
# ---------------------------------------------------------------------------


class TestGetUtcRangeForAstanaDate:
    def test_start_before_end(self):
        d = date(2026, 6, 13)
        start, end = CashbackService._get_utc_range_for_astana_date(d)
        assert start < end

    def test_start_is_midnight_utc(self):
        d = date(2026, 6, 13)
        start, _ = CashbackService._get_utc_range_for_astana_date(d)
        assert start.hour == 0
        assert start.minute == 0
        assert start.second == 0

    def test_end_is_end_of_day_utc(self):
        d = date(2026, 6, 13)
        _, end = CashbackService._get_utc_range_for_astana_date(d)
        assert end.hour == 23
        assert end.minute == 59
        assert end.second == 59

    def test_result_is_aware_utc(self):
        d = date(2026, 6, 13)
        start, end = CashbackService._get_utc_range_for_astana_date(d)
        assert start.tzinfo == UTC
        assert end.tzinfo == UTC

    def test_different_dates_give_different_ranges(self):
        start1, _ = CashbackService._get_utc_range_for_astana_date(date(2026, 6, 13))
        start2, _ = CashbackService._get_utc_range_for_astana_date(date(2026, 6, 14))
        assert start1 != start2


# ---------------------------------------------------------------------------
# _get_astana_now and _get_astana_today (smoke tests)
# ---------------------------------------------------------------------------


def test_get_astana_now_is_utc_plus_5():
    now_utc = datetime.now(UTC)
    astana_now = CashbackService._get_astana_now()
    # _get_astana_now() adds ASTANA_OFFSET (5h) to UTC.now(), keeping UTC tzinfo.
    delta = astana_now - now_utc  # both aware (UTC tzinfo)
    assert abs(delta.total_seconds() - 5 * 3600) < 2


def test_get_astana_today_is_date():
    today = CashbackService._get_astana_today()
    assert isinstance(today, date)


# ---------------------------------------------------------------------------
# check_and_update — state machine
# ---------------------------------------------------------------------------


class TestCheckAndUpdateAlreadyCompleted:
    def test_already_completed_today_is_idempotent(self):
        state = _fake_state(current_day_in_streak=3)
        uow = _uow_with_state(state=state, existing_today=SimpleNamespace(id=1))
        svc = _make_service(uow=uow)
        svc.check_and_update(uuid4())
        # commit should only be called for the get_user_state path (create state if missing)
        uow.cashback.create_daily_completion.assert_not_called()


class TestCheckAndUpdateNoState:
    def test_no_state_creates_state(self):
        uow = MagicMock()
        uow.__enter__ = lambda s: s
        uow.__exit__ = MagicMock(return_value=False)
        # First call (get_user_state) returns None → creates state
        # Second call (for the main block) also returns fresh state
        fresh_state = _fake_state()
        uow.cashback.get_user_state.side_effect = [None, fresh_state]
        uow.cashback.get_daily_completion.return_value = SimpleNamespace(id=1)  # already done
        svc = _make_service(uow=uow)
        svc.check_and_update(uuid4())
        uow.cashback.create_user_state.assert_called_once()


class TestCheckAndUpdateConditionsNotMet:
    def test_conditions_not_met_no_progress(self):
        state = _fake_state(current_day_in_streak=2)
        uow = _uow_with_state(state=state, existing_today=None,
                               all_conditions_met=False)
        svc = _make_service(uow=uow)
        svc.check_and_update(uuid4())
        # daily completion NOT created, no bank deposit
        uow.cashback.create_daily_completion.assert_not_called()
        svc._bank_service.deposit.assert_not_called()


class TestCheckAndUpdateProgressDay:
    def test_progress_increments_day_in_streak(self):
        state = _fake_state(current_streak_number=1, current_day_in_streak=2)
        uow = _uow_with_state(state=state, existing_today=None, all_conditions_met=True)
        svc = _make_service(uow=uow)
        svc.check_and_update(uuid4())
        assert state.current_day_in_streak == 3

    def test_progress_creates_daily_completion(self):
        state = _fake_state(current_day_in_streak=1)
        uow = _uow_with_state(state=state, existing_today=None, all_conditions_met=True)
        svc = _make_service(uow=uow)
        svc.check_and_update(uuid4())
        uow.cashback.create_daily_completion.assert_called_once()

    def test_progress_commits(self):
        state = _fake_state(current_day_in_streak=1)
        uow = _uow_with_state(state=state, existing_today=None, all_conditions_met=True)
        svc = _make_service(uow=uow)
        svc.check_and_update(uuid4())
        uow.commit.assert_called()


class TestCheckAndUpdateReward:
    def test_completing_day_5_earns_reward(self):
        state = _fake_state(
            current_streak_number=1,
            current_day_in_streak=4,  # about to complete day 5
            total_cashback_earned=0,
            total_streaks_completed=0,
        )
        uow = _uow_with_state(state=state, existing_today=None, all_conditions_met=True)
        bank = MagicMock()
        svc = _make_service(uow=uow, bank=bank)
        svc.check_and_update(uuid4())
        # Should deposit REWARD_AMOUNT
        bank.deposit.assert_called_once()
        call_kwargs = bank.deposit.call_args[1]
        assert call_kwargs["amount"] == CashbackService.REWARD_AMOUNT
        assert state.total_cashback_earned == CashbackService.REWARD_AMOUNT
        assert state.total_streaks_completed == 1

    def test_completing_day_5_advances_streak_number(self):
        state = _fake_state(
            current_streak_number=2,
            current_day_in_streak=4,
        )
        uow = _uow_with_state(state=state, existing_today=None, all_conditions_met=True)
        svc = _make_service(uow=uow)
        svc.check_and_update(uuid4())
        # streak 2 + 1 = 3, day resets to 0
        assert state.current_streak_number == 3
        assert state.current_day_in_streak == 0

    def test_completing_streak_at_max_wraps_to_1(self):
        state = _fake_state(
            current_streak_number=CashbackService.MAX_STREAKS,  # 6
            current_day_in_streak=4,
        )
        uow = _uow_with_state(state=state, existing_today=None, all_conditions_met=True)
        svc = _make_service(uow=uow)
        svc.check_and_update(uuid4())
        # at MAX_STREAKS (6), wraps back to 1
        assert state.current_streak_number == 1
        assert state.current_day_in_streak == 0

    def test_mid_streak_no_reward_no_deposit(self):
        state = _fake_state(current_day_in_streak=2)
        uow = _uow_with_state(state=state, existing_today=None, all_conditions_met=True)
        bank = MagicMock()
        svc = _make_service(uow=uow, bank=bank)
        svc.check_and_update(uuid4())
        bank.deposit.assert_not_called()


class TestCheckAndUpdateStreakReset:
    def test_gap_resets_streak_to_day_1(self):
        yesterday = CashbackService._get_astana_today() - timedelta(days=1)
        # last completion was day before yesterday → gap
        two_days_ago = yesterday - timedelta(days=1)
        last_comp = SimpleNamespace(completion_date=two_days_ago)
        state = _fake_state(
            current_streak_number=3,
            current_day_in_streak=4,
            last_completed_date=two_days_ago,
        )
        uow = _uow_with_state(state=state, existing_today=None,
                               last_completion=last_comp, all_conditions_met=True)
        svc = _make_service(uow=uow)
        svc.check_and_update(uuid4())
        # streak was reset: starts from 1 and day 0 → after progress: day=1
        assert state.current_streak_number == 1
        assert state.current_day_in_streak == 1
