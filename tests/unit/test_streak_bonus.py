"""Pin StreakBonus DTO + tier-resolution rules.

The «correct coins for streak N» calculation is the core business
logic — admin moves thresholds around (1→100, 7→200, 30→500) and
the service has to pick the right one. These tests pin the
edge cases so a refactor doesn't quietly shift what the modal
shows.
"""

from datetime import date as _date
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import quiz.models  # noqa: F401 — orm registry
import student.models  # noqa: F401

from streak_bonus.dtos import (
    StreakPushTemplateUpdateDTO,
    StreakRewardTierCreateDTO,
    StreakRewardTierUpdateDTO,
)
from streak_bonus.service import StreakBonusService


def _tier(min_streak: int, coins: int, is_active: bool = True):
    return SimpleNamespace(
        min_streak=min_streak,
        coins=coins,
        is_active=is_active,
    )


def _make_service(*, tiers=None, claim_for_today=None, balance=0):
    repo = MagicMock()
    repo.db = MagicMock()
    repo.list_tiers.return_value = tiers or []
    repo.get_claim_for_date.return_value = claim_for_today
    bank = MagicMock()
    bank.get_or_create_account.return_value = SimpleNamespace(balance=balance)
    bank.deposit.return_value = None
    svc = StreakBonusService(repo=repo, bank_service=bank)
    return svc, repo, bank


# ─── DTO validation ──────────────────────────────────────────────────


class TestCreateDTO:
    def test_min_streak_must_be_positive(self):
        with pytest.raises(ValidationError):
            StreakRewardTierCreateDTO(min_streak=0, coins=100)

    def test_min_streak_capped_at_365(self):
        with pytest.raises(ValidationError):
            StreakRewardTierCreateDTO(min_streak=366, coins=100)

    def test_coins_must_be_non_negative(self):
        with pytest.raises(ValidationError):
            StreakRewardTierCreateDTO(min_streak=1, coins=-10)

    def test_coins_capped_at_100k(self):
        with pytest.raises(ValidationError):
            StreakRewardTierCreateDTO(min_streak=1, coins=100_001)

    def test_is_active_defaults_true(self):
        dto = StreakRewardTierCreateDTO(min_streak=1, coins=100)
        assert dto.is_active is True


class TestUpdateDTO:
    def test_all_fields_optional(self):
        dto = StreakRewardTierUpdateDTO()
        assert dto.coins is None
        assert dto.is_active is None

    def test_partial_patch_validates_bounds(self):
        with pytest.raises(ValidationError):
            StreakRewardTierUpdateDTO(coins=-1)


# ─── tier resolution (the «coins for streak N» logic) ───────────────


class TestCoinsForStreak:
    """Pin the «pick the largest active tier where min_streak <= N»
    rule. Admin can leave gaps (only 1 and 30 configured); user with
    streak 7 should fall to the 1-tier, not skip past."""

    DEFAULT_TIERS = [
        _tier(1, 100),
        _tier(7, 200),
        _tier(30, 500),
    ]

    def test_zero_streak_yields_zero(self):
        svc, *_ = _make_service(tiers=self.DEFAULT_TIERS)
        assert svc._coins_for_streak(0) == 0

    def test_negative_streak_yields_zero(self):
        # Defensive — clamp instead of throwing
        svc, *_ = _make_service(tiers=self.DEFAULT_TIERS)
        assert svc._coins_for_streak(-5) == 0

    def test_picks_day1_for_streak_1(self):
        svc, *_ = _make_service(tiers=self.DEFAULT_TIERS)
        assert svc._coins_for_streak(1) == 100

    def test_picks_day1_for_streak_6_below_day7_threshold(self):
        svc, *_ = _make_service(tiers=self.DEFAULT_TIERS)
        assert svc._coins_for_streak(6) == 100

    def test_picks_day7_at_threshold(self):
        svc, *_ = _make_service(tiers=self.DEFAULT_TIERS)
        assert svc._coins_for_streak(7) == 200

    def test_picks_day7_above_until_day30(self):
        svc, *_ = _make_service(tiers=self.DEFAULT_TIERS)
        assert svc._coins_for_streak(29) == 200

    def test_picks_day30_at_threshold(self):
        svc, *_ = _make_service(tiers=self.DEFAULT_TIERS)
        assert svc._coins_for_streak(30) == 500

    def test_picks_day30_for_streak_999(self):
        svc, *_ = _make_service(tiers=self.DEFAULT_TIERS)
        assert svc._coins_for_streak(999) == 500

    def test_inactive_tier_is_skipped(self):
        # Operator disabled the day-7 tier — streak 7 falls back to day-1
        tiers = [
            _tier(1, 100),
            _tier(7, 200, is_active=False),  # disabled
        ]
        repo = MagicMock()
        repo.db = MagicMock()
        # list_tiers(only_active=True) is called inside _coins_for_streak;
        # honor the filter here so the disabled row doesn't get returned.
        repo.list_tiers.side_effect = lambda only_active=False: (
            [t for t in tiers if t.is_active] if only_active else tiers
        )
        repo.get_claim_for_date.return_value = None
        bank = MagicMock()
        bank.get_or_create_account.return_value = SimpleNamespace(balance=0)
        svc = StreakBonusService(repo=repo, bank_service=bank)
        assert svc._coins_for_streak(7) == 100

    def test_empty_tier_list_yields_zero(self):
        svc, *_ = _make_service(tiers=[])
        assert svc._coins_for_streak(5) == 0


# ─── claim rules ─────────────────────────────────────────────────────


class TestClaim:
    DEFAULT_TIERS = [_tier(1, 100), _tier(7, 200), _tier(30, 500)]

    def test_zero_streak_rejected(self):
        svc, *_ = _make_service(tiers=self.DEFAULT_TIERS)
        with pytest.raises(HTTPException) as e:
            svc.claim(uuid4(), 0)
        assert e.value.status_code == 400
        assert "стрика" in e.value.detail.lower()

    def test_already_claimed_today_rejected(self):
        existing = SimpleNamespace(id=1)
        svc, *_ = _make_service(
            tiers=self.DEFAULT_TIERS,
            claim_for_today=existing,
        )
        with pytest.raises(HTTPException) as e:
            svc.claim(uuid4(), 5)
        assert e.value.status_code == 409
        assert "уже" in e.value.detail.lower()

    def test_no_tier_rejected(self):
        # Streak 5, no tiers in DB → reward 0 → 400
        svc, *_ = _make_service(tiers=[])
        with pytest.raises(HTTPException) as e:
            svc.claim(uuid4(), 5)
        assert e.value.status_code == 400
        assert "не настроена" in e.value.detail.lower()


# ─── status (read-only snapshot for iOS modal) ───────────────────────


class TestStatus:
    DEFAULT_TIERS = [_tier(1, 100), _tier(7, 200), _tier(30, 500)]

    def test_zero_streak_status_has_no_reward(self):
        svc, *_ = _make_service(tiers=self.DEFAULT_TIERS, balance=42)
        out = svc.get_status(uuid4(), 0)
        assert out.current_streak == 0
        assert out.has_claimed_today is False
        assert out.reward_coins == 0
        assert out.claim_date is None
        assert out.balance == 42

    def test_active_streak_no_claim_yet_offers_reward(self):
        svc, *_ = _make_service(tiers=self.DEFAULT_TIERS, balance=200)
        out = svc.get_status(uuid4(), 8)
        assert out.current_streak == 8
        assert out.has_claimed_today is False
        assert out.reward_coins == 200  # day-7 tier
        assert out.claim_date is not None
        assert out.balance == 200

    def test_already_claimed_status_reflects_existing(self):
        existing = SimpleNamespace(id=1, coins_credited=200, claim_date=_date.today())
        svc, *_ = _make_service(
            tiers=self.DEFAULT_TIERS,
            claim_for_today=existing,
            balance=200,
        )
        out = svc.get_status(uuid4(), 8)
        assert out.has_claimed_today is True
        assert out.reward_coins == 200
        assert out.balance == 200


# ─── Push template (singleton admin) ─────────────────────────────────


class TestPushTemplateDTO:
    def test_hours_before_reset_must_be_within_day(self):
        with pytest.raises(ValidationError):
            StreakPushTemplateUpdateDTO(hours_before_reset=0)
        with pytest.raises(ValidationError):
            StreakPushTemplateUpdateDTO(hours_before_reset=24)

    def test_title_length_bounded(self):
        with pytest.raises(ValidationError):
            StreakPushTemplateUpdateDTO(title="")
        with pytest.raises(ValidationError):
            StreakPushTemplateUpdateDTO(title="x" * 201)

    def test_body_length_bounded(self):
        with pytest.raises(ValidationError):
            StreakPushTemplateUpdateDTO(body="")
        with pytest.raises(ValidationError):
            StreakPushTemplateUpdateDTO(body="x" * 501)

    def test_all_fields_optional_for_partial_patch(self):
        # Editing only the body without touching enabled/offset must
        # be valid so the admin form can submit a single field.
        dto = StreakPushTemplateUpdateDTO(body="new body")
        assert dto.enabled is None
        assert dto.title is None
        assert dto.body == "new body"


class TestPushTemplateService:
    def _make_template(self, **overrides):
        base = dict(
            enabled=True,
            title="Не теряй стрик!",
            body="У тебя {streak} дн.",
            hours_before_reset=8,
            timezone="Asia/Almaty",
        )
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_get_template_missing_raises_404(self):
        svc, repo, _ = _make_service()
        repo.get_push_template.return_value = None
        with pytest.raises(HTTPException) as exc:
            svc.get_push_template()
        assert exc.value.status_code == 404

    def test_update_template_applies_partial_patch(self):
        svc, repo, _ = _make_service()
        template = self._make_template()
        repo.get_push_template.return_value = template

        out = svc.update_push_template(
            StreakPushTemplateUpdateDTO(body="новый текст", hours_before_reset=12)
        )

        assert out.body == "новый текст"
        assert out.hours_before_reset == 12
        # Unchanged fields stay put.
        assert out.title == "Не теряй стрик!"
        assert out.enabled is True
        repo.db.flush.assert_called_once()

    def test_update_template_toggle_disabled(self):
        svc, repo, _ = _make_service()
        template = self._make_template(enabled=True)
        repo.get_push_template.return_value = template

        out = svc.update_push_template(StreakPushTemplateUpdateDTO(enabled=False))

        assert out.enabled is False


# ─── Reminder service body templating ───────────────────────────────


class TestReminderRendering:
    """The `{streak}` placeholder substitution is the only piece of
    logic that runs per audience group. Pin its forgiving behavior so
    an operator typing a body without the placeholder doesn't blow up
    the cron mid-batch."""

    def test_renders_streak_placeholder(self):
        from streak_bonus.reminder_service import StreakReminderService

        out = StreakReminderService._render("У тебя {streak} дн.", streak=14)
        assert out == "У тебя 14 дн."

    def test_no_placeholder_passes_through(self):
        from streak_bonus.reminder_service import StreakReminderService

        out = StreakReminderService._render("Не теряй стрик!", streak=14)
        assert out == "Не теряй стрик!"

    def test_unknown_placeholder_falls_back_to_raw(self):
        from streak_bonus.reminder_service import StreakReminderService

        # Operator typo {streaks} would normally raise KeyError on
        # .format() — `_render` swallows it so the cron survives.
        out = StreakReminderService._render("{streaks} дн.", streak=14)
        assert out == "{streaks} дн."
