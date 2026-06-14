"""Tests for ReferralService — code minting, format validation, and
the redeem-rule enforcement that the iOS UI shows as friendly errors.

Don't touch the DB here — every test passes a `MagicMock` Session +
mocked AdminUserService/UserPointsRepository/AppSettingsService. The
goal is to pin the business contract (one promo per account, no
self-redemption, snapshot of policy at redemption time) so a refactor
doesn't silently change what error a user sees.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

# Register all ORM models so SQLAlchemy mapper relationship resolution
# doesn't fail when ReferralService calls db.query(Payment) inside
# _has_ever_paid() — Payment mapper needs Subscription, and Subscription
# needs Payment; all must be registered before any query is executed.
import payments.models  # noqa: F401
import quiz.models  # noqa: F401
import student.models  # noqa: F401
import subscription.models  # noqa: F401
from referrals.dtos import ReferralPolicyDTO
from referrals.service import ReferralService, _CODE_FORMAT_RE


def _fake_code(user_id, code):
    """ReferralCode-like object. We don't import the real SQLAlchemy
    model because instantiating it forces mapper init which would pull
    in the entire ORM registry — overkill for a pure-logic test."""
    return SimpleNamespace(user_id=user_id, code=code, created_at=None)


def _fake_redemption():
    return SimpleNamespace(id=1)


# ─── helpers ──────────────────────────────────────────────────────────


def _make_service(
    db_mock=None,
    policy: ReferralPolicyDTO | None = None,
    admin_user_service=None,
    user_points_repo=None,
    file_service=None,
    cap: int = 99999,
):
    """Wire a ReferralService against fully-mocked collaborators."""
    if db_mock is None:
        db_mock = MagicMock()
    if policy is None:
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
        admin_user_service=admin_user_service or MagicMock(),
        user_points_repo=user_points_repo or MagicMock(),
        file_service=file_service or MagicMock(),
    )


def _query_returns(db_mock, *return_values):
    """Set up `db.query(...).filter(...).first()` to return values
    in order across successive `.query(...)` calls."""
    chain_mocks = [MagicMock() for _ in return_values]
    for chain, val in zip(chain_mocks, return_values):
        chain.filter.return_value.first.return_value = val
    db_mock.query.side_effect = chain_mocks


def _setup_redeem_queries(db_mock, owner, prior=None, rewarded_count=0,
                          inviter_paid=True, cap=99999):
    """Wire the sequential queries a full redeem() issues:
      1. ReferralCode lookup (.first)            → owner
      2. already-redeemed pre-check (.first)     → prior
      3. anti-farm cap COUNT (.count)            → rewarded_count
      4. _has_ever_paid Payment lookup (.first)  → payment row or None
         (only reached when reward_inviter=True, i.e. rewarded_count < cap)
    Pass cap= matching the value used in _make_service(cap=) so the
    reward_inviter calculation stays in sync.
    """
    code_chain = MagicMock()
    code_chain.filter.return_value.first.return_value = owner
    prior_chain = MagicMock()
    prior_chain.filter.return_value.first.return_value = prior
    cap_chain = MagicMock()
    cap_chain.filter.return_value.count.return_value = rewarded_count
    payment_chain = MagicMock()
    payment_chain.filter.return_value.first.return_value = (
        SimpleNamespace(id=1) if inviter_paid else None
    )
    side_effects = [code_chain, prior_chain, cap_chain]
    # Payment query only reached when reward_inviter=True (rewarded_count < cap)
    if rewarded_count < cap:
        side_effects.append(payment_chain)
    db_mock.query.side_effect = side_effects


# ─── _generate_code shape ─────────────────────────────────────────────


class TestGenerateCode:
    """The format is part of the user-visible contract — show on profile,
    type by hand. Don't let a refactor accidentally widen the character
    set or change the length."""

    def test_matches_expected_format(self):
        for _ in range(50):
            code = ReferralService._generate_code()
            assert _CODE_FORMAT_RE.match(code), f"{code!r} fails format"

    def test_length_is_8(self):
        assert len(ReferralService._generate_code()) == 8

    def test_no_ambiguous_letters(self):
        # Operator picked alphabet minus O/I/L on 27.05.2026 so users
        # don't misread codes off a screenshot. Pin that.
        bad = set("OIL")
        for _ in range(200):
            code = ReferralService._generate_code()
            # The 3-digit middle is fine; check the 5 letters.
            letters = code[:3] + code[6:8]
            assert not (bad & set(letters)), f"{code} contains ambiguous letter"


# ─── _mask_phone fallback ─────────────────────────────────────────────


class TestMaskPhone:
    def test_keeps_last_4_digits(self):
        assert ReferralService._mask_phone("+77787943760") == "+…3760"

    def test_handles_no_phone(self):
        assert ReferralService._mask_phone(None) == "—"
        assert ReferralService._mask_phone("") == "—"

    def test_short_phone_falls_back(self):
        # Less than 4 digits — not a real phone, show placeholder.
        assert ReferralService._mask_phone("12") == "—"


# ─── format guards on redeem() ────────────────────────────────────────


class TestRedeemFormatValidation:
    def test_accepts_lowercase_after_uppercasing(self):
        # Case-insensitive entry — lowercase should pass format guard
        # and proceed to DB lookup. Stub the lookup as "not found" to
        # confirm the code crossed the format gate.
        db = MagicMock()
        _query_returns(db, None)
        svc = _make_service(db_mock=db)
        with pytest.raises(HTTPException) as e:
            svc.redeem(invitee_id=uuid4(), code="ejw123jx")
        # 404 (not 400) proves the format passed.
        assert e.value.status_code == 404

    def test_rejects_short_garbage(self):
        svc = _make_service()
        with pytest.raises(HTTPException) as e:
            svc.redeem(invitee_id=uuid4(), code="ABC")
        assert e.value.status_code == 400
        assert "формат" in e.value.detail.lower()

    def test_rejects_wrong_pattern(self):
        # Right length, wrong shape (no digits in middle).
        svc = _make_service()
        with pytest.raises(HTTPException) as e:
            svc.redeem(invitee_id=uuid4(), code="ABCDEFGH")
        assert e.value.status_code == 400


# ─── core redeem rules ────────────────────────────────────────────────


class TestRedeemRules:
    def test_unknown_code_yields_404(self):
        db = MagicMock()
        _query_returns(db, None)  # code lookup → not found
        svc = _make_service(db_mock=db)
        with pytest.raises(HTTPException) as e:
            svc.redeem(invitee_id=uuid4(), code="EJW123JX")
        assert e.value.status_code == 404
        assert "не существует" in e.value.detail

    def test_self_redemption_yields_400(self):
        owner_id = uuid4()
        owner = _fake_code(owner_id, "EJW123JX")
        db = MagicMock()
        _query_returns(db, owner)
        svc = _make_service(db_mock=db)
        with pytest.raises(HTTPException) as e:
            svc.redeem(invitee_id=owner_id, code="EJW123JX")
        assert e.value.status_code == 400
        assert "собственный" in e.value.detail.lower()

    def test_already_redeemed_yields_409(self):
        owner = _fake_code(uuid4(), "EJW123JX")
        existing = _fake_redemption()
        db = MagicMock()
        _query_returns(db, owner, existing)
        svc = _make_service(db_mock=db)
        with pytest.raises(HTTPException) as e:
            svc.redeem(invitee_id=uuid4(), code="EJW123JX")
        assert e.value.status_code == 409
        assert "уже использовал" in e.value.detail.lower()

    def test_successful_redemption_grants_both_sides(self):
        owner_id = uuid4()
        invitee_id = uuid4()
        owner = _fake_code(owner_id, "EJW123JX")
        db = MagicMock()
        # owner exists, no prior redemption, inviter well under the cap
        _setup_redeem_queries(db, owner, prior=None, rewarded_count=0)
        admin = MagicMock()
        points = MagicMock()
        svc = _make_service(
            db_mock=db,
            admin_user_service=admin,
            user_points_repo=points,
        )

        result = svc.redeem(invitee_id=invitee_id, code="EJW123JX")

        # Invitee rewards are DEFERRED (granted on first payment via
        # grant_pending_invitee_reward()). Only inviter is rewarded immediately.
        points.add_points.assert_called_once_with(owner_id, 100)

        # Inviter Pro days granted immediately; invitee days are deferred.
        admin.grant_pro_subscription.assert_called_once_with(user_id=owner_id, days=7)

        # Response DTO carries the full snapshot (deferred amounts are still visible).
        assert result.inviter_id == owner_id
        assert result.invitee_stars_granted == 30
        assert result.invitee_days_granted == 7
        assert result.inviter_stars_granted == 100
        assert result.inviter_days_granted == 7
        assert result.invitee_reward_pending is True

    def test_pro_grant_failure_does_not_block_redemption(self):
        # The redemption row is the source-of-truth for "this user used
        # their one allowed code". If Keycloak hiccups while granting
        # Pro days, the row must still commit so the user can't
        # re-redeem; an admin can manually re-issue the missing days.
        owner_id = uuid4()
        owner = _fake_code(owner_id, "EJW123JX")
        db = MagicMock()
        _setup_redeem_queries(db, owner, prior=None, rewarded_count=0)
        admin = MagicMock()
        admin.grant_pro_subscription.side_effect = RuntimeError("keycloak down")
        svc = _make_service(db_mock=db, admin_user_service=admin)

        # Should NOT raise — the redemption commits BEFORE the (failing)
        # post-commit Pro-day grant, so the user can't re-redeem.
        result = svc.redeem(invitee_id=uuid4(), code="EJW123JX")
        assert result.inviter_id == owner_id
        db.commit.assert_called_once()


# ─── anti-farm cap ────────────────────────────────────────────────────


class TestInviterCap:
    """Past `referral_inviter_max_rewards` (default 25) the invitee still
    gets their bonus but the inviter earns nothing — kills self-code
    farming via throwaway accounts."""

    def test_under_cap_rewards_both_sides(self):
        owner_id = uuid4()
        owner = _fake_code(owner_id, "EJW123JX")
        db = MagicMock()
        # cap=25: 24 < 25 → reward_inviter=True → Payment query included
        _setup_redeem_queries(db, owner, prior=None, rewarded_count=24, cap=25)
        points = MagicMock()
        svc = _make_service(db_mock=db, user_points_repo=points, cap=25)

        result = svc.redeem(invitee_id=uuid4(), code="EJW123JX")

        # Invitee stars are deferred; only inviter gets stars immediately.
        assert points.add_points.call_count == 1
        points.add_points.assert_called_once_with(owner_id, 100)
        assert result.inviter_stars_granted == 100
        assert result.inviter_days_granted == 7

    def test_at_cap_rewards_invitee_only(self):
        owner_id = uuid4()
        invitee_id = uuid4()
        owner = _fake_code(owner_id, "EJW123JX")
        db = MagicMock()
        # cap=25: rewarded_count==cap → reward_inviter=False → no Payment query needed
        _setup_redeem_queries(db, owner, prior=None, rewarded_count=25, cap=25)
        admin = MagicMock()
        points = MagicMock()
        svc = _make_service(
            db_mock=db, admin_user_service=admin, user_points_repo=points, cap=25
        )

        result = svc.redeem(invitee_id=invitee_id, code="EJW123JX")

        # Inviter at cap → no inviter rewards at all.
        # Invitee stars/days are DEFERRED (granted on first payment),
        # so add_points and grant_pro_subscription are NOT called immediately.
        points.add_points.assert_not_called()
        admin.grant_pro_subscription.assert_not_called()
        # DTO still carries the deferred invitee snapshot.
        assert result.invitee_stars_granted == 30
        assert result.inviter_stars_granted == 0
        assert result.inviter_days_granted == 0
        assert result.invitee_reward_pending is True


# ─── concurrent-redeem race ───────────────────────────────────────────


class TestRedeemRace:
    """A concurrent second redemption for the same invitee loses the
    unique-constraint race at commit → friendly 409, nothing credited."""

    def _race_service(self):
        owner = _fake_code(uuid4(), "EJW123JX")
        db = MagicMock()
        _setup_redeem_queries(db, owner, prior=None, rewarded_count=0)
        db.commit.side_effect = IntegrityError("INSERT", {}, Exception("dup"))
        return db, owner

    def test_race_loser_yields_409(self):
        db, _ = self._race_service()
        svc = _make_service(db_mock=db)
        with pytest.raises(HTTPException) as e:
            svc.redeem(invitee_id=uuid4(), code="EJW123JX")
        assert e.value.status_code == 409
        assert e.value.headers["X-Error-Code"] == "already_redeemed"
        db.rollback.assert_called_once()

    def test_race_loser_does_not_grant_pro(self):
        # Pro days are a non-transactional Keycloak write — the loser must
        # NEVER reach the grant, or it would leak Pro with no redemption.
        db, _ = self._race_service()
        admin = MagicMock()
        svc = _make_service(db_mock=db, admin_user_service=admin)
        with pytest.raises(HTTPException):
            svc.redeem(invitee_id=uuid4(), code="EJW123JX")
        admin.grant_pro_subscription.assert_not_called()


# ─── machine-readable error codes (X-Error-Code header) ───────────────


class TestErrorCodes:
    """Every business-rule rejection carries an X-Error-Code header so the
    KZ app can localize instead of printing the raw Russian `detail`."""

    def test_bad_format_header(self):
        svc = _make_service()
        with pytest.raises(HTTPException) as e:
            svc.redeem(invitee_id=uuid4(), code="ABC")
        assert e.value.headers["X-Error-Code"] == "bad_format"

    def test_unknown_code_header(self):
        db = MagicMock()
        _query_returns(db, None)
        svc = _make_service(db_mock=db)
        with pytest.raises(HTTPException) as e:
            svc.redeem(invitee_id=uuid4(), code="EJW123JX")
        assert e.value.headers["X-Error-Code"] == "unknown"

    def test_self_code_header(self):
        owner_id = uuid4()
        owner = _fake_code(owner_id, "EJW123JX")
        db = MagicMock()
        _query_returns(db, owner)
        svc = _make_service(db_mock=db)
        with pytest.raises(HTTPException) as e:
            svc.redeem(invitee_id=owner_id, code="EJW123JX")
        assert e.value.headers["X-Error-Code"] == "self_code"

    def test_already_redeemed_header(self):
        owner = _fake_code(uuid4(), "EJW123JX")
        existing = _fake_redemption()
        db = MagicMock()
        _query_returns(db, owner, existing)
        svc = _make_service(db_mock=db)
        with pytest.raises(HTTPException) as e:
            svc.redeem(invitee_id=uuid4(), code="EJW123JX")
        assert e.value.headers["X-Error-Code"] == "already_redeemed"


# ─── policy read ──────────────────────────────────────────────────────


class TestPolicy:
    def test_reads_all_four_keys_with_defaults(self):
        svc = _make_service(
            policy=ReferralPolicyDTO(
                inviter_stars=200, inviter_days=14,
                invitee_stars=50, invitee_days=10,
            )
        )
        policy = svc.get_policy()
        assert policy.inviter_stars == 200
        assert policy.inviter_days == 14
        assert policy.invitee_stars == 50
        assert policy.invitee_days == 10


# ─── code uniqueness on mint ──────────────────────────────────────────


class TestCodeUniqueness:
    def test_format_regex_matches_real_codes(self):
        # Sanity: regex matches anything _generate_code produces.
        for _ in range(20):
            code = ReferralService._generate_code()
            assert _CODE_FORMAT_RE.match(code)

    def test_format_regex_rejects_close_variants(self):
        # 7 chars, 9 chars, wrong middle.
        for bad in ["EJW123J", "EJW123JXX", "EJ12345X", "EJWWWWJX", "1JW123JX"]:
            assert not _CODE_FORMAT_RE.match(bad), f"{bad} unexpectedly matches"
