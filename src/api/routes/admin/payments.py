"""Admin endpoints for payment management."""

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.dependencies import allow_only_admins, get_database, get_db_session, get_payment_settings, get_settings
from clients.freedom_pay.settings import FreedomPaySettings
from clients.freedom_pay.poller import _check_payment_status
from database import Database
from payments.models import Payment
from settings import Settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/payments",
    tags=["admin"],
    dependencies=[Depends(allow_only_admins)],
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
