"""Tests for the referral_disabled gate in ReferralService.redeem().

When an inviter's UserRiskProfile has referral_disabled=True, the
inviter_stars_granted must be 0 — the invitee still gets their bonus.

Uses the same helper pattern as test_referral_service.py.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import payments.models   # noqa: F401 — register ORM mappers
import quiz.models       # noqa: F401
import student.models    # noqa: F401
import subscription.models  # noqa: F401
from referrals.dtos import ReferralPolicyDTO
from referrals.service import ReferralService


# ---------------------------------------------------------------------------
# Helpers (duplicated from test_referral_service to keep tests independent)
# ---------------------------------------------------------------------------

def _make_service(db_mock=None, cap: int = 99999):
    if db_mock is None:
        db_mock = MagicMock()
    policy = ReferralPolicyDTO(
        inviter_stars=100, inviter_days=7,
        invitee_stars=30, invitee_days=7,
    )
    app_settings = MagicMock()
    app_settings.get_int.side_effect = lambda key, default: {
        "referral_inviter_stars": policy.inviter_stars,
        "referral_inviter_days": policy.inviter_days,
        "referral_invitee_stars": policy.invitee_stars,
        "referral_invitee_days": policy.invitee_days,
        "referral_inviter_max_rewards": cap,
    }.get(key, default)
    return ReferralService(
        db=db_mock,
        app_settings=app_settings,
        admin_user_service=MagicMock(),
        user_points_repo=MagicMock(),
        file_service=MagicMock(),
    )


def _fake_owner(user_id=None, code="ABC123DE"):
    uid = user_id or uuid4()
    return SimpleNamespace(user_id=uid, code=code, created_at=None)


def _setup_redeem_queries(
    db_mock,
    owner,
    prior=None,
    rewarded_count: int = 0,
    risk_profile=None,
    inviter_paid: bool = True,
    cap: int = 99999,
):
    """Wire sequential db.query() calls for a full redeem() execution:
      1. ReferralCode lookup
      2. Already-redeemed pre-check
      3. Anti-farm cap COUNT
      4. UserRiskProfile check          (only when reward_inviter=True)
      5. _has_ever_paid Payment lookup  (only when reward_inviter=True)
    """
    code_chain   = MagicMock(); code_chain.filter.return_value.first.return_value  = owner
    prior_chain  = MagicMock(); prior_chain.filter.return_value.first.return_value = prior
    cap_chain    = MagicMock(); cap_chain.filter.return_value.count.return_value    = rewarded_count
    risk_chain   = MagicMock(); risk_chain.filter.return_value.first.return_value   = risk_profile
    pay_chain    = MagicMock()
    pay_chain.filter.return_value.first.return_value = (
        SimpleNamespace(id=1) if inviter_paid else None
    )
    side_effects = [code_chain, prior_chain, cap_chain]
    if rewarded_count < cap:
        side_effects += [risk_chain, pay_chain]
    db_mock.query.side_effect = side_effects


# ---------------------------------------------------------------------------
# Tests: referral_disabled blocks inviter reward
# ---------------------------------------------------------------------------

class TestReferralDisabledGate:
    def test_inviter_gets_zero_stars_when_disabled(self):
        inviter_id = uuid4()
        owner = _fake_owner(user_id=inviter_id)
        db = MagicMock()
        _setup_redeem_queries(
            db, owner,
            risk_profile=SimpleNamespace(referral_disabled=True),
            inviter_paid=True,
        )
        svc = _make_service(db_mock=db)
        db.add = MagicMock()
        db.commit = MagicMock()

        svc.redeem(invitee_id=uuid4(), code="ABC123DE")

        added = db.add.call_args[0][0]
        assert added.inviter_stars_granted == 0, (
            "referral_disabled=True must zero out inviter stars"
        )

    def test_inviter_gets_stars_when_not_disabled(self):
        inviter_id = uuid4()
        owner = _fake_owner(user_id=inviter_id)
        db = MagicMock()
        _setup_redeem_queries(
            db, owner,
            risk_profile=SimpleNamespace(referral_disabled=False),
            inviter_paid=True,
        )
        svc = _make_service(db_mock=db)
        db.add = MagicMock()
        db.commit = MagicMock()

        svc.redeem(invitee_id=uuid4(), code="ABC123DE")

        added = db.add.call_args[0][0]
        assert added.inviter_stars_granted == 100, (
            "referral_disabled=False should not block inviter stars"
        )

    def test_inviter_gets_stars_when_no_risk_profile(self):
        """No risk profile row at all → treat as not disabled."""
        owner = _fake_owner()
        db = MagicMock()
        _setup_redeem_queries(
            db, owner,
            risk_profile=None,
            inviter_paid=True,
        )
        svc = _make_service(db_mock=db)
        db.add = MagicMock()
        db.commit = MagicMock()

        svc.redeem(invitee_id=uuid4(), code="ABC123DE")

        added = db.add.call_args[0][0]
        assert added.inviter_stars_granted == 100

    def test_invitee_bonus_unaffected_by_referral_disabled(self):
        """Invitee stars should still be 30 regardless of inviter's disabled flag."""
        owner = _fake_owner()
        db = MagicMock()
        _setup_redeem_queries(
            db, owner,
            risk_profile=SimpleNamespace(referral_disabled=True),
            inviter_paid=True,
        )
        svc = _make_service(db_mock=db)
        db.add = MagicMock()
        db.commit = MagicMock()

        svc.redeem(invitee_id=uuid4(), code="ABC123DE")

        added = db.add.call_args[0][0]
        assert added.invitee_stars_granted == 30, (
            "Invitee bonus must not be affected by inviter's referral_disabled flag"
        )

    def test_disabled_and_inviter_unpaid_both_zero(self):
        """Both disabled AND unpaid — inviter gets 0 either way."""
        owner = _fake_owner()
        db = MagicMock()
        _setup_redeem_queries(
            db, owner,
            risk_profile=SimpleNamespace(referral_disabled=True),
            inviter_paid=False,
        )
        svc = _make_service(db_mock=db)
        db.add = MagicMock()
        db.commit = MagicMock()

        svc.redeem(invitee_id=uuid4(), code="ABC123DE")

        added = db.add.call_args[0][0]
        assert added.inviter_stars_granted == 0
