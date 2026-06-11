"""Admin endpoints for payment management."""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.dependencies import allow_only_admins, get_db_session, get_payment_settings
from clients.freedom_pay.settings import FreedomPaySettings
from clients.freedom_pay.poller import _check_payment_status
from payments.models import Payment

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/payments",
    tags=["admin"],
    dependencies=[Depends(allow_only_admins)],
)


class PollResultDTO(BaseModel):
    checked: int
    updated_to_paid: int
    updated_to_failed: int
    still_pending: int


@router.post("/poll-pending", response_model=PollResultDTO)
async def poll_pending_now(
    session: Session = Depends(get_db_session),
    freedom_settings: FreedomPaySettings = Depends(get_payment_settings),
):
    """Force-check all pending FreedomPay payments right now.

    Bypasses the 25-minute poller interval. Useful for recovering payments
    that got stuck because the webhook callback never arrived.
    Ignores attempts_count and last_polled_at limits — checks everything
    with status='pending'.
    """

    pending = (
        session.query(Payment)
        .filter(Payment.status == "pending")
        .limit(200)
        .all()
    )

    before_statuses = {p.id: p.status for p in pending}

    for payment in pending:
        try:
            payment.last_polled_at = None  # reset so poller picks up
            await _check_payment_status(payment, freedom_settings, session)
        except Exception:
            logger.exception("poll-pending-now: error checking payment %s", payment.id)

    updated_to_paid = sum(
        1 for p in pending if before_statuses[p.id] != "paid" and p.status == "paid"
    )
    updated_to_failed = sum(
        1 for p in pending if before_statuses[p.id] not in ("failed",) and p.status == "failed"
    )
    still_pending = sum(1 for p in pending if p.status == "pending")

    logger.info(
        "poll-pending-now: checked=%d paid=%d failed=%d pending=%d",
        len(pending),
        updated_to_paid,
        updated_to_failed,
        still_pending,
    )

    return PollResultDTO(
        checked=len(pending),
        updated_to_paid=updated_to_paid,
        updated_to_failed=updated_to_failed,
        still_pending=still_pending,
    )
