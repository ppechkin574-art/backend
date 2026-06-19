"""reconcile_registration_trial — anti-farming for the registration trial.

`complete_registration` always grants a fresh 1-day trial. `reconcile_*`
reconciles it against the persistent phone ledger (`trial_history`):

- phone never seen             → record it, KEEP the trial.
- phone in ledger + paywall ON   → REVOKE (set FREE).
- phone in ledger + paywall OFF  → keep (today's behaviour), no double-record.
- no phone (email registration)  → skip entirely (used_trial gates it).
- DB hiccup                     → non-raising; user keeps the trial.
- TRIAL_DURATION_MINUTES > 0    → QA shortener re-stamps the trial end.

The method is SYNC (called from the async registration route as a plain call),
so these tests call it directly without await.
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
    # plan=PRO simulates the 1-day trial complete_registration just granted.
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


# ──────────────────────────── tests ────────────────────────────


def test_new_phone_records_and_keeps_trial(monkeypatch):
    monkeypatch.delenv("TRIAL_PAYWALL_ENABLED", raising=False)
    monkeypatch.delenv("TRIAL_DURATION_MINUTES", raising=False)
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()

    out = _svc(db, auth).reconcile_registration_trial(_make_user())

    assert any(s.added for s in db._sessions), "ledger row should be inserted"
    assert out.plan == PlanType.PRO, "trial must stay for a never-seen phone"
    assert auth.updates == [], "no Keycloak write when keeping the trial"


def test_known_phone_paywall_on_revokes(monkeypatch):
    monkeypatch.setenv("TRIAL_PAYWALL_ENABLED", "true")
    monkeypatch.delenv("TRIAL_DURATION_MINUTES", raising=False)
    existing = TrialHistory(phone_hash=_hash_phone("+77787943760"))
    db = _FakeDatabase(existing_rows=[existing])
    auth = _FakeAuthService()

    out = _svc(db, auth).reconcile_registration_trial(_make_user())

    assert len(auth.updates) == 1, "should revoke via one Keycloak write"
    assert auth.updates[0].plan == PlanType.FREE
    assert auth.updates[0].subscription_end is None
    assert out.plan == PlanType.FREE
    assert all(not s.added for s in db._sessions), "no double-record"


def test_known_phone_paywall_off_keeps_trial(monkeypatch):
    monkeypatch.delenv("TRIAL_PAYWALL_ENABLED", raising=False)  # default OFF
    monkeypatch.delenv("TRIAL_DURATION_MINUTES", raising=False)
    existing = TrialHistory(phone_hash=_hash_phone("+77787943760"))
    db = _FakeDatabase(existing_rows=[existing])
    auth = _FakeAuthService()

    out = _svc(db, auth).reconcile_registration_trial(_make_user())

    assert auth.updates == [], "flag off → no revoke (today's behaviour)"
    assert out.plan == PlanType.PRO
    assert all(not s.added for s in db._sessions), "already recorded → no insert"


def test_no_phone_skips_entirely(monkeypatch):
    monkeypatch.setenv("TRIAL_PAYWALL_ENABLED", "true")
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()

    out = _svc(db, auth).reconcile_registration_trial(_make_user(phone=None))

    assert auth.updates == []
    assert out.plan == PlanType.PRO
    assert db._sessions == [], "email-only users never touch the ledger"


def test_new_phone_paywall_on_still_keeps_trial(monkeypatch):
    # anti-farming fires only for KNOWN phones; a brand-new phone keeps its trial
    monkeypatch.setenv("TRIAL_PAYWALL_ENABLED", "true")
    monkeypatch.delenv("TRIAL_DURATION_MINUTES", raising=False)
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()

    out = _svc(db, auth).reconcile_registration_trial(_make_user())

    assert any(s.added for s in db._sessions)
    assert out.plan == PlanType.PRO
    assert auth.updates == []


def test_db_failure_is_non_fatal(monkeypatch):
    monkeypatch.delenv("TRIAL_PAYWALL_ENABLED", raising=False)
    monkeypatch.delenv("TRIAL_DURATION_MINUTES", raising=False)
    db = _FakeDatabase(existing_rows=[], insert_fails=True)
    auth = _FakeAuthService()

    # Must NOT raise — a ledger hiccup can't break registration.
    out = _svc(db, auth).reconcile_registration_trial(_make_user())

    assert out.plan == PlanType.PRO
    assert any(s.rolled_back for s in db._sessions)


def test_qa_shortener_restamps_trial(monkeypatch):
    monkeypatch.delenv("TRIAL_PAYWALL_ENABLED", raising=False)
    monkeypatch.setenv("TRIAL_DURATION_MINUTES", "5")
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()

    out = _svc(db, auth).reconcile_registration_trial(_make_user())

    assert len(auth.updates) == 1, "shortener should re-stamp the trial once"
    assert auth.updates[0].plan == PlanType.PRO
    assert auth.updates[0].subscription_end is not None
    assert out.plan == PlanType.PRO


# ───────────────── reconcile_login_trial (existing users) ─────────────────


def test_login_flag_off_is_noop(monkeypatch):
    monkeypatch.delenv("TRIAL_PAYWALL_ENABLED", raising=False)
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()

    out = _svc(db, auth).reconcile_login_trial(_make_user(plan=PlanType.FREE))

    assert auth.updates == []
    assert db._sessions == [], "flag off → no DB touch at all"
    assert out.plan == PlanType.FREE


def test_login_grants_existing_free_user(monkeypatch):
    monkeypatch.setenv("TRIAL_PAYWALL_ENABLED", "true")
    monkeypatch.delenv("TRIAL_DURATION_MINUTES", raising=False)
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()

    out = _svc(db, auth).reconcile_login_trial(_make_user(plan=PlanType.FREE))

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

    out = _svc(db, auth).reconcile_login_trial(_make_user(plan=PlanType.FREE))

    assert auth.updates == [], "phone already used its one trial → must buy"
    assert out.plan == PlanType.FREE


def test_login_active_pro_untouched(monkeypatch):
    monkeypatch.setenv("TRIAL_PAYWALL_ENABLED", "true")
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()
    future = datetime.now(UTC) + timedelta(days=10)

    out = _svc(db, auth).reconcile_login_trial(
        _make_user(plan=PlanType.PRO, subscription_end=future)
    )

    assert auth.updates == [], "an active payer must not be disturbed"
    assert db._sessions == [], "no ledger touch for active PRO"
    assert out.subscription_end == future


def test_login_no_phone_skips(monkeypatch):
    monkeypatch.setenv("TRIAL_PAYWALL_ENABLED", "true")
    db = _FakeDatabase(existing_rows=[])
    auth = _FakeAuthService()

    out = _svc(db, auth).reconcile_login_trial(
        _make_user(phone=None, plan=PlanType.FREE)
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
    out = _svc(db, auth).reconcile_login_trial(_make_user(plan=PlanType.FREE))

    assert out.plan == PlanType.FREE
    # Grant failed BEFORE recording → phone not blacklisted (can retry later).
    assert all(not s.added for s in db._sessions)
