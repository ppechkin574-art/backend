"""Admin endpoints for payment management."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.dependencies import (
    allow_read_or_admin_write,
    get_database,
    get_db_session,
    get_payment_settings,
    get_settings,
    get_user_repository_keycloak,
)
from auth.dtos.users import UserQueryDTO
from auth.repositories import UserRepositoryInterface
from clients.freedom_pay.settings import FreedomPaySettings
from clients.freedom_pay.poller import _check_payment_status
from database import Database
from payments.models import Payment
from settings import Settings
from subscription.event_log import SubscriptionEventLog

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/payments",
    tags=["admin"],
    dependencies=[Depends(allow_read_or_admin_write)],
)


class PollStartDTO(BaseModel):
    started: bool
    pending_count: int
    message: str


async def _run_poll_in_background(freedom_settings: FreedomPaySettings, db: Database) -> None:
    """Check all pending FreedomPay payments. Runs as a background task so the
    HTTP response returns immediately instead of blocking for minutes."""
    try:
        with db.session as session:
            pending = (
                session.query(Payment)
                .filter(Payment.status == "pending")
                .limit(200)
                .all()
            )
            logger.info("poll-pending-bg: found %d pending payments", len(pending))

            paid = failed = 0
            for payment in pending:
                try:
                    old_status = payment.status
                    await _check_payment_status(payment, freedom_settings, session)
                    if old_status != "paid" and payment.status == "paid":
                        paid += 1
                    elif old_status != "failed" and payment.status == "failed":
                        failed += 1
                except Exception:
                    logger.exception("poll-pending-bg: error on payment %s", payment.id)

            logger.info(
                "poll-pending-bg: done. paid=%d failed=%d still_pending=%d",
                paid,
                failed,
                len(pending) - paid - failed,
            )
    except Exception:
        logger.exception("poll-pending-bg: critical error")


@router.post("/poll-pending", response_model=PollStartDTO)
async def poll_pending_now(
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db_session),
    freedom_settings: FreedomPaySettings = Depends(get_payment_settings),
    db: Database = Depends(get_database),
):
    """Trigger background check of all pending FreedomPay payments.

    Returns immediately — the actual polling (up to 200 requests to FreedomPay)
    runs in the background. Check Railway logs for results, or refresh the
    Finance page in ~1-2 minutes.
    """
    pending_count = session.query(Payment).filter(Payment.status == "pending").count()
    background_tasks.add_task(_run_poll_in_background, freedom_settings, db)

    logger.info("poll-pending: background task queued for %d payments", pending_count)

    return PollStartDTO(
        started=True,
        pending_count=pending_count,
        message=f"Запущено в фоне: {pending_count} платежей. Обновите страницу через 1-2 минуты.",
    )


@router.get("/iap-events")
def iap_events(
    platform: str = "apple",
    status: str | None = None,
    days: int = 30,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_db_session),
    users: UserRepositoryInterface = Depends(get_user_repository_keycloak),
):
    """IAP (in-app purchase) event monitor for the Finance page.

    Reads the `subscription_event_log` audit trail and returns:
      - summary counts (success / failed / flagged / total),
      - a paginated list of events with the user's name + phone resolved.

    Defaults to iOS (platform="apple"): purchases, renewals, expiries, refunds,
    revokes, verify rejections, shared-account flags. `status` filters the list
    (e.g. "failed"); `days` bounds the window.
    """
    since = datetime.now(UTC) - timedelta(days=max(1, days))
    base = session.query(SubscriptionEventLog).filter(
        SubscriptionEventLog.platform == platform,
        SubscriptionEventLog.created_at >= since,
    )

    by_status = dict(
        base.with_entities(SubscriptionEventLog.status, func.count())
        .group_by(SubscriptionEventLog.status)
        .all()
    )
    summary = {
        "total": sum(by_status.values()),
        "success": by_status.get("success", 0),
        "failed": by_status.get("failed", 0),
        "flagged": by_status.get("flagged", 0),
    }

    q = base
    if status:
        q = q.filter(SubscriptionEventLog.status == status)
    filtered_total = q.count()
    page = (
        q.order_by(SubscriptionEventLog.created_at.desc())
        .offset(max(0, offset))
        .limit(min(200, max(1, limit)))
        .all()
    )

    # Resolve name + phone per unique user_id (operator chose richer rows).
    user_map: dict[str, dict] = {}
    for uid in {r.user_id for r in page if r.user_id}:
        try:
            u = users.get(UserQueryDTO(id=UUID(uid)))
            user_map[uid] = {
                "name": getattr(u, "name", None),
                "phone": getattr(u, "phone", None),
            }
        except Exception:  # noqa: BLE001 — a missing/deleted user must not 500
            user_map[uid] = {"name": None, "phone": None}

    items = [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "event_type": r.event_type,
            "status": r.status,
            "user_id": r.user_id,
            "user_name": (user_map.get(r.user_id) or {}).get("name"),
            "user_phone": (user_map.get(r.user_id) or {}).get("phone"),
            "product_id": r.product_id,
            "transaction_id": r.transaction_id,
            "amount": float(r.amount) if r.amount is not None else None,
            "environment": r.environment,
            "detail": r.detail,
        }
        for r in page
    ]

    return {
        "summary": summary,
        "total": filtered_total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }
