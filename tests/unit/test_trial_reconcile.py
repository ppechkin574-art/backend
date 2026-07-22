"""Trial reconciliation — anti-farming + one-time trial for existing users,
with the trial length driven by an admin-configurable duration (passed in as
`trial_days`; app_settings `trial_duration_days`).

reconcile_registration_trial(user, trial_days):
- phone never seen             → record it, stamp the trial to trial_days.
- phone in ledger + paywall ON    → REVOKE (set FREE).
- phone in ledger + paywall OFF   → keep, stamp to trial_days, no double-record.
- no phone (email)             → skip entirely.
- DB hiccup                    → non-raising; user keeps the registration trial.

reconcile_login_trial(user, trial_days):
- flag OFF                     → no-op.
- existing FREE user, new phone → grant trial_days, record.
- phone in ledger              → no grant (must buy).
- active PRO                   → untouched.
- no phone / grant failure     → safe no-op.

TRIAL_DURATION_MINUTES env (if >0) overrides trial_days for QA.
Both methods are SYNC (called from the async routes as plain calls).
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

# Eager model imports so SQLAlchemy can resolve relationships when we build a
# TrialHistory instance (mirrors test_trial_per_phone.py).
from payments import models as _payment_models  # noqa: F401
from promocodes import models as _promocode_models  # noqa: F401

from auth.dtos.users import UserDTO, UserUpdateDTO
from common.enums import PlanType
from subscription.models import TrialHistory
from subscription.service import SubscriptionService, _hash_phone


# ──────────────────────────── fakes ────────────────────────────


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_args):
        return self

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, existing=None, insert_fails=False):
        self._existing = existing or []
        self._insert_fails = insert_fails
        self.added = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def query(self, _model):
        return _FakeQuery(self._existing)

    def add(self, row):
        if self._insert_fails:
            raise RuntimeError("simulated DB write failure")
        self.added.append(row)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class _FakeDatabase:
    def __init__(self, *, existing_rows=None, insert_fails=False):
        self._sessions = []
        self._existing = existing_rows or []
        self._insert_fails = insert_fails

    @property
    def session(self):
        s = _FakeSession(self._existing, self._insert_fails)
        self._sessions.append(s)
        return s


class _FakeAuthService:
    def __init__(self):
        self.updates: list[UserUpdateDTO] = []

    def update_user_profile(self, user: UserDTO, update: UserUpdateDTO) -> UserDTO:
        self.updates.append(update)
        return user.model_copy(
            update={
                "plan": update.plan if update.plan is not None else user.plan,
                "subscription_end": update.subscription_end,
            }
        )


def _make_user(
    *,
    phone="+77787943760",
    plan=PlanType.PRO,
    used_trial=True,
    subscription_end=None,
) -> UserDTO:
    # plan=PRO simulates the placeholder 1-day trial complete_registration grants.
    return UserDTO(
        id=uuid4(),
        username="u",
        name="U",
        email="u@example.com",
        phone=phone,
        plan=plan,
        used_trial=used_trial,
        subscription_end=subscription_end,
        is_active=True,
    )


def _svc(db, auth) -> SubscriptionService:
    return SubscriptionService(auth_service=auth, database=db)


# ───────────────── reconcile_registration_trial ─────────────────


def test_new_phone_records_and_stamps_trial(monkeypatch):
    monkeypatch.delenv("TRIAL_PAYWALL_ENABLED", raising=False)
    monkeypatch.delenv("TRIAL_DURATION_MINUTES", raising=False)
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()

    out = _svc(db, auth).reconcile_registration_trial(_make_user(), 1)

    assert any(s.added for s in db._sessions), "ledger row should be inserted"
    assert len(auth.updates) == 1, "trial stamped to the configured duration"
    assert auth.updates[0].plan == PlanType.PRO
    assert auth.updates[0].subscription_end is not None
    assert out.plan == PlanType.PRO


def test_registration_uses_configured_duration(monkeypatch):
    monkeypatch.delenv("TRIAL_PAYWALL_ENABLED", raising=False)
    monkeypatch.delenv("TRIAL_DURATION_MINUTES", raising=False)
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()
    before = datetime.now(UTC)

    _svc(db, auth).reconcile_registration_trial(_make_user(), 3)

    end = auth.updates[0].subscription_end
    delta = end - before
    assert timedelta(days=2, hours=23) < delta < timedelta(days=3, hours=1), (
        f"expected ~3 days, got {delta}"
    )


def test_registration_preserves_longer_auto_grant(monkeypatch):
    # complete_registration() just granted `new_user_pro_days` (e.g. 365) via
    # subscription_end BEFORE this reconcile call runs — it must not be
    # clobbered back down to the much shorter default trial_duration_days.
    monkeypatch.delenv("TRIAL_PAYWALL_ENABLED", raising=False)
    monkeypatch.delenv("TRIAL_DURATION_MINUTES", raising=False)
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()
    auto_grant_end = datetime.now(UTC) + timedelta(days=365)

    out = _svc(db, auth).reconcile_registration_trial(
        _make_user(subscription_end=auto_grant_end), 1
    )

    end = auth.updates[0].subscription_end
    assert end == auto_grant_end, (
        f"365-day auto-grant should survive reconcile, got {end}"
    )
    assert out.plan == PlanType.PRO


def test_registration_still_extends_when_existing_end_is_shorter(monkeypatch):
    # The reverse case: existing subscription_end is shorter than the
    # configured trial_days — reconcile should still extend up to trial_days
    # (this is the pre-existing, already-correct behaviour; guards against a
    # fix that always keeps `existing_end` instead of taking the max).
    monkeypatch.delenv("TRIAL_PAYWALL_ENABLED", raising=False)
    monkeypatch.delenv("TRIAL_DURATION_MINUTES", raising=False)
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()
    before = datetime.now(UTC)
    short_end = before + timedelta(hours=1)

    _svc(db, auth).reconcile_registration_trial(_make_user(subscription_end=short_end), 3)

    end = auth.updates[0].subscription_end
    delta = end - before
    assert timedelta(days=2, hours=23) < delta < timedelta(days=3, hours=1), (
        f"expected ~3 days (trial_days should win over the shorter existing end), got {delta}"
    )


def test_known_phone_paywall_on_revokes(monkeypatch):
    monkeypatch.setenv("TRIAL_PAYWALL_ENABLED", "true")
    monkeypatch.delenv("TRIAL_DURATION_MINUTES", raising=False)
    existing = TrialHistory(phone_hash=_hash_phone("+77787943760"))
    db = _FakeDatabase(existing_rows=[existing])
    auth = _FakeAuthService()

    out = _svc(db, auth).reconcile_registration_trial(_make_user(), 1)

    assert len(auth.updates) == 1, "should revoke via one Keycloak write"
    assert auth.updates[0].plan == PlanType.FREE
    assert auth.updates[0].subscription_end is None
    assert out.plan == PlanType.FREE
    assert all(not s.added for s in db._sessions), "no double-record"


def test_known_phone_paywall_off_keeps_and_stamps(monkeypatch):
    monkeypatch.delenv("TRIAL_PAYWALL_ENABLED", raising=False)  # default OFF
    monkeypatch.delenv("TRIAL_DURATION_MINUTES", raising=False)
    existing = TrialHistory(phone_hash=_hash_phone("+77787943760"))
    db = _FakeDatabase(existing_rows=[existing])
    auth = _FakeAuthService()

    out = _svc(db, auth).reconcile_registration_trial(_make_user(), 1)

    assert len(auth.updates) == 1, "flag off → keep + stamp (no revoke)"
    assert auth.updates[0].plan == PlanType.PRO
    assert out.plan == PlanType.PRO
    assert all(not s.added for s in db._sessions), "already recorded → no insert"


def test_no_phone_skips_entirely(monkeypatch):
    monkeypatch.setenv("TRIAL_PAYWALL_ENABLED", "true")
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()

    out = _svc(db, auth).reconcile_registration_trial(_make_user(phone=None), 1)

    assert auth.updates == []
    assert out.plan == PlanType.PRO
    assert db._sessions == [], "email-only users never touch the ledger"


def test_new_phone_paywall_on_still_keeps_trial(monkeypatch):
    # anti-farming fires only for KNOWN phones; a brand-new phone keeps its trial
    monkeypatch.setenv("TRIAL_PAYWALL_ENABLED", "true")
    monkeypatch.delenv("TRIAL_DURATION_MINUTES", raising=False)
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()

    out = _svc(db, auth).reconcile_registration_trial(_make_user(), 1)

    assert any(s.added for s in db._sessions)
    assert out.plan == PlanType.PRO
    assert auth.updates[0].plan == PlanType.PRO  # stamped, not revoked


def test_db_failure_is_non_fatal(monkeypatch):
    monkeypatch.delenv("TRIAL_PAYWALL_ENABLED", raising=False)
    monkeypatch.delenv("TRIAL_DURATION_MINUTES", raising=False)
    db = _FakeDatabase(existing_rows=[], insert_fails=True)
    auth = _FakeAuthService()

    # Must NOT raise — a ledger hiccup can't break registration.
    out = _svc(db, auth).reconcile_registration_trial(_make_user(), 1)

    assert out.plan == PlanType.PRO
    assert any(s.rolled_back for s in db._sessions)
    assert auth.updates == [], "stamp is skipped when the ledger write failed"


def test_qa_minutes_override_wins(monkeypatch):
    monkeypatch.delenv("TRIAL_PAYWALL_ENABLED", raising=False)
    monkeypatch.setenv("TRIAL_DURATION_MINUTES", "5")
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()
    before = datetime.now(UTC)

    _svc(db, auth).reconcile_registration_trial(_make_user(), 30)  # 30 days config

    end = auth.updates[0].subscription_end
    delta = end - before
    assert delta < timedelta(hours=1), f"env minutes should win, got {delta}"


# ───────────────── reconcile_login_trial (existing users) ─────────────────


def test_login_flag_off_is_noop(monkeypatch):
    monkeypatch.delenv("TRIAL_PAYWALL_ENABLED", raising=False)
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()

    out = _svc(db, auth).reconcile_login_trial(_make_user(plan=PlanType.FREE), 1)

    assert auth.updates == []
    assert db._sessions == [], "flag off → no DB touch at all"
    assert out.plan == PlanType.FREE


def test_login_grants_existing_free_user(monkeypatch):
    monkeypatch.setenv("TRIAL_PAYWALL_ENABLED", "true")
    monkeypatch.delenv("TRIAL_DURATION_MINUTES", raising=False)
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()

    out = _svc(db, auth).reconcile_login_trial(_make_user(plan=PlanType.FREE), 1)

    assert len(auth.updates) == 1, "should grant a one-time trial"
    assert auth.updates[0].plan == PlanType.PRO
    assert auth.updates[0].subscription_end is not None
    assert out.plan == PlanType.PRO
    assert any(s.added for s in db._sessions), "grant must be recorded"


def test_login_known_phone_no_grant(monkeypatch):
    monkeypatch.setenv("TRIAL_PAYWALL_ENABLED", "true")
    existing = TrialHistory(phone_hash=_hash_phone("+77787943760"))
    db = _FakeDatabase(existing_rows=[existing])
    auth = _FakeAuthService()

    out = _svc(db, auth).reconcile_login_trial(_make_user(plan=PlanType.FREE), 1)

    assert auth.updates == [], "phone already used its one trial → must buy"
    assert out.plan == PlanType.FREE


def test_login_active_pro_untouched(monkeypatch):
    monkeypatch.setenv("TRIAL_PAYWALL_ENABLED", "true")
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()
    future = datetime.now(UTC) + timedelta(days=10)

    out = _svc(db, auth).reconcile_login_trial(
        _make_user(plan=PlanType.PRO, subscription_end=future), 1
    )

    assert auth.updates == [], "an active payer must not be disturbed"
    assert db._sessions == [], "no ledger touch for active PRO"
    assert out.subscription_end == future


def test_login_no_phone_skips(monkeypatch):
    monkeypatch.setenv("TRIAL_PAYWALL_ENABLED", "true")
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()

    out = _svc(db, auth).reconcile_login_trial(
        _make_user(phone=None, plan=PlanType.FREE), 1
    )

    assert auth.updates == []
    assert db._sessions == []


def test_login_grant_keycloak_failure_non_fatal(monkeypatch):
    monkeypatch.setenv("TRIAL_PAYWALL_ENABLED", "true")
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()

    def _boom(*_a, **_k):
        raise RuntimeError("keycloak down")

    auth.update_user_profile = _boom

    # Must NOT raise — a grant hiccup can't break login.
    out = _svc(db, auth).reconcile_login_trial(_make_user(plan=PlanType.FREE), 1)

    assert out.plan == PlanType.FREE
    # Grant failed BEFORE recording → phone not blacklisted (can retry later).
    assert all(not s.added for s in db._sessions)
