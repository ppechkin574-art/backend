"""Unit tests for PromocodeService.activate_promocode.

Covers:
1.  Successful activation: PromocodeUsage created, activations_count incremented,
    subscription_service called.
2.  Code not found → 404.
3.  Code expired → 400.
4.  Max activations reached → 400.
5.  Non-reusable code + same user activates twice → 400, count rolled back.
6.  Reusable code → same user can activate multiple times.
7.  Subscription grant failure → usage row still committed (audit trail).
8.  Atomic increment: rowcount=0 path distinguished from rowcount=1.

All tests use fakes — no DB, no network.
"""

import pytest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException

# Register all ORM models so SQLAlchemy mapper resolves cross-model relationships.
import quiz.models  # noqa: F401
import student.models  # noqa: F401
import payments.models  # noqa: F401
import subscription.models  # noqa: F401


# ─── helpers ──────────────────────────────────────────────────────────


def _fake_user(user_id=None):
    u = SimpleNamespace()
    u.id = user_id or uuid4()
    u.plan = "FREE"
    u.subscription_end = None
    return u


def _fake_promocode(
    code="PROMO30",
    plan_type="PRO",
    duration_days=30,
    max_activations=100,
    activations_count=0,
    expires_at=None,
    is_trial=False,
    is_reusable=False,
    pid=1,
):
    p = MagicMock()
    p.id = pid
    p.code = code
    p.plan_type = plan_type
    p.duration_days = duration_days
    p.max_activations = max_activations
    p.activations_count = activations_count
    p.expires_at = expires_at
    p.is_trial = is_trial
    p.is_reusable = is_reusable
    return p


def _make_service(
    *,
    update_rowcount=1,
    promocode_after_update=None,
    existing_usage=None,
    subscription_service=None,
):
    """Wire PromocodeService with a fully mocked SQLAlchemy session.

    update_rowcount — what `session.execute(UPDATE).rowcount` returns.
    promocode_after_update — the Promocode row returned by `query().filter().first()`.
    existing_usage — PromocodeUsage row for the second `query().filter().first()` call.
    """
    from promocodes.service import PromocodeService

    session = MagicMock()

    # Mock session.execute(...).rowcount
    execute_result = MagicMock()
    execute_result.rowcount = update_rowcount
    session.execute.return_value = execute_result

    # Mock session.query(...).filter(...).first() calls in order:
    # 1st call (after rowcount=0): fetch promocode for error detail
    # 1st call (after rowcount=1): fetch updated promocode
    # 2nd call (rowcount=1, non-reusable): fetch existing usage
    promo_chain = MagicMock()
    promo_chain.filter.return_value.first.return_value = promocode_after_update

    usage_chain = MagicMock()
    usage_chain.filter.return_value.first.return_value = existing_usage

    session.query.side_effect = [promo_chain, usage_chain, promo_chain]

    sub_svc = subscription_service or AsyncMock()

    return PromocodeService(db_session=session, subscription_service=sub_svc), session


# ─── successful activation ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_successful_activation_returns_dto():
    promo = _fake_promocode()
    user = _fake_user()
    svc, session = _make_service(
        update_rowcount=1,
        promocode_after_update=promo,
        existing_usage=None,
    )

    result = await svc.activate_promocode(user, "PROMO30")

    assert result.success is True
    assert result.plan == "PRO"
    assert result.duration_days == 30
    assert result.promocode_id == promo.id


@pytest.mark.asyncio
async def test_successful_activation_creates_usage_row():
    promo = _fake_promocode()
    user = _fake_user()
    svc, session = _make_service(
        update_rowcount=1,
        promocode_after_update=promo,
        existing_usage=None,
    )

    await svc.activate_promocode(user, "PROMO30")

    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    from promocodes.models import PromocodeUsage
    assert isinstance(added, PromocodeUsage)
    assert str(added.student_guid) == str(user.id)
    assert added.promocode_id == promo.id


@pytest.mark.asyncio
async def test_successful_activation_calls_subscription_service():
    promo = _fake_promocode(duration_days=7)
    user = _fake_user()
    sub_svc = AsyncMock()
    svc, _ = _make_service(
        update_rowcount=1,
        promocode_after_update=promo,
        subscription_service=sub_svc,
    )

    await svc.activate_promocode(user, "PROMO30")

    sub_svc.activate_subscription.assert_awaited_once()
    call_kwargs = sub_svc.activate_subscription.await_args
    assert call_kwargs.args[1].value == "PRO"
    assert call_kwargs.kwargs["expires_at"] is not None


@pytest.mark.asyncio
async def test_successful_activation_commits():
    promo = _fake_promocode()
    user = _fake_user()
    svc, session = _make_service(
        update_rowcount=1,
        promocode_after_update=promo,
    )

    await svc.activate_promocode(user, "PROMO30")

    session.commit.assert_called_once()


# ─── atomic increment guard ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_rowcount_zero_returns_404_when_code_not_found():
    svc, session = _make_service(
        update_rowcount=0,
        promocode_after_update=None,  # code doesn't exist
    )
    with pytest.raises(HTTPException) as exc:
        await svc.activate_promocode(_fake_user(), "BADCODE")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_rowcount_zero_returns_400_when_expired():
    expired = _fake_promocode(
        expires_at=datetime.now(UTC) - timedelta(days=1),
        activations_count=0,
    )
    svc, _ = _make_service(
        update_rowcount=0,
        promocode_after_update=expired,
    )
    with pytest.raises(HTTPException) as exc:
        await svc.activate_promocode(_fake_user(), "PROMO30")
    assert exc.value.status_code == 400
    assert "истёк" in exc.value.detail


@pytest.mark.asyncio
async def test_rowcount_zero_returns_400_when_max_activations_reached():
    full = _fake_promocode(max_activations=5, activations_count=5)
    svc, _ = _make_service(
        update_rowcount=0,
        promocode_after_update=full,
    )
    with pytest.raises(HTTPException) as exc:
        await svc.activate_promocode(_fake_user(), "PROMO30")
    assert exc.value.status_code == 400
    assert "максимальное" in exc.value.detail


# ─── one-per-user for non-reusable ────────────────────────────────────


@pytest.mark.asyncio
async def test_non_reusable_second_use_rolls_back_and_raises():
    promo = _fake_promocode(is_reusable=False)
    user = _fake_user()
    existing_usage = MagicMock()  # user already has a usage row

    from promocodes.service import PromocodeService
    session = MagicMock()
    execute_result = MagicMock()
    execute_result.rowcount = 1
    session.execute.return_value = execute_result

    promo_chain = MagicMock()
    promo_chain.filter.return_value.first.return_value = promo
    usage_chain = MagicMock()
    usage_chain.filter.return_value.first.return_value = existing_usage

    session.query.side_effect = [promo_chain, usage_chain]

    svc = PromocodeService(db_session=session, subscription_service=AsyncMock())
    with pytest.raises(HTTPException) as exc:
        await svc.activate_promocode(user, "PROMO30")

    assert exc.value.status_code == 400
    assert "уже использовали" in exc.value.detail

    # Rollback increment was issued (second execute call is the decrement).
    assert session.execute.call_count == 2
    session.commit.assert_called_once()  # commit the rollback


@pytest.mark.asyncio
async def test_reusable_code_allows_same_user_multiple_times():
    promo = _fake_promocode(is_reusable=True)
    user = _fake_user()
    svc, session = _make_service(
        update_rowcount=1,
        promocode_after_update=promo,
        existing_usage=MagicMock(),  # existing usage — but reusable, so ignored
    )

    # Should NOT raise
    result = await svc.activate_promocode(user, "PROMO30")
    assert result.success is True


# ─── subscription grant failure is non-fatal ──────────────────────────


@pytest.mark.asyncio
async def test_subscription_grant_failure_still_commits_usage():
    promo = _fake_promocode()
    user = _fake_user()
    sub_svc = AsyncMock()
    sub_svc.activate_subscription.side_effect = RuntimeError("Keycloak down")

    svc, session = _make_service(
        update_rowcount=1,
        promocode_after_update=promo,
        subscription_service=sub_svc,
    )

    # Should NOT raise — usage row is the audit trail.
    result = await svc.activate_promocode(user, "PROMO30")
    assert result.success is True
    session.commit.assert_called_once()
    session.add.assert_called_once()  # PromocodeUsage was added


# ─── validate_promocode (info-only, no side effects) ──────────────────


@pytest.mark.asyncio
async def test_validate_rejects_expired_code():
    from promocodes.service import PromocodeService
    session = MagicMock()
    expired = _fake_promocode(expires_at=datetime.now(UTC) - timedelta(days=1))
    chain = MagicMock()
    chain.filter.return_value.first.return_value = expired
    session.query.return_value = chain

    svc = PromocodeService(db_session=session, subscription_service=AsyncMock())
    with pytest.raises(HTTPException) as exc:
        await svc.validate_promocode("PROMO30")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_validate_rejects_exhausted_code():
    from promocodes.service import PromocodeService
    session = MagicMock()
    full = _fake_promocode(max_activations=3, activations_count=3)
    chain = MagicMock()
    chain.filter.return_value.first.return_value = full
    session.query.return_value = chain

    svc = PromocodeService(db_session=session, subscription_service=AsyncMock())
    with pytest.raises(HTTPException) as exc:
        await svc.validate_promocode("PROMO30")
    assert exc.value.status_code == 400
    assert "максимальное" in exc.value.detail


@pytest.mark.asyncio
async def test_validate_rejects_unknown_code():
    from promocodes.service import PromocodeService
    session = MagicMock()
    chain = MagicMock()
    chain.filter.return_value.first.return_value = None
    session.query.return_value = chain

    svc = PromocodeService(db_session=session, subscription_service=AsyncMock())
    with pytest.raises(HTTPException) as exc:
        await svc.validate_promocode("BADCODE")
    assert exc.value.status_code == 404


# ─── create_promocode duplicate check ─────────────────────────────────


@pytest.mark.asyncio
async def test_create_rejects_duplicate_code():
    from promocodes.service import PromocodeService
    from promocodes.dtos import PromocodeCreateDTO
    from common.enums import PlanType

    session = MagicMock()
    chain = MagicMock()
    chain.filter.return_value.first.return_value = _fake_promocode()  # already exists
    session.query.return_value = chain

    svc = PromocodeService(db_session=session, subscription_service=AsyncMock())
    dto = PromocodeCreateDTO(
        code="PROMO30",
        plan_type=PlanType.PRO,
        duration_days=30,
        max_activations=10,
        created_by=str(uuid4()),
    )
    with pytest.raises(HTTPException) as exc:
        await svc.create_promocode(dto)
    assert exc.value.status_code == 400
    assert "уже существует" in exc.value.detail
