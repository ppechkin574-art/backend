import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime, timedelta

import defusedxml.ElementTree as ET
from sqlalchemy.orm import Session

from clients.freedom_pay.client import get_payment_info
from clients.freedom_pay.settings import FreedomPaySettings
from database.database import Database
from database.settings import DatabaseSettings
from payments.models import Payment, PaymentStatusHistory

logger = logging.getLogger(__name__)

POLL_INTERVAL_MINUTES = 25
STALE_THRESHOLD_MINUTES = 10
MAX_ATTEMPTS = 10


async def poll_pending_payments(freedom_settings: FreedomPaySettings, db_settings: DatabaseSettings):
    """Фоновая задача для проверки статусов pending платежей"""
    db = Database(db_settings)

    while True:
        try:
            logger.info("Starting payment status poller cycle")

            with db.session as session:
                cutoff_time = datetime.now(UTC) - timedelta(minutes=STALE_THRESHOLD_MINUTES)
                max_attempts_cutoff = MAX_ATTEMPTS

                pending_payments = (
                    session.query(Payment)
                    .filter(
                        Payment.status == "pending",
                        Payment.attempts_count < max_attempts_cutoff,
                        Payment.last_polled_at < cutoff_time,
                    )
                    .limit(100)
                    .all()
                )

                logger.info("Found %d pending payments to check", len(pending_payments))

                for payment in pending_payments:
                    try:
                        await _check_payment_status(payment, freedom_settings, session)
                    except Exception as e:
                        logger.exception(
                            "Error checking payment status: payment_id=%s, order_id=%s, error=%s",
                            payment.id,
                            payment.order_id,
                            str(e),
                        )
                        payment.attempts_count = (payment.attempts_count or 0) + 1
                        payment.last_polled_at = datetime.now(UTC)
                        session.commit()

            logger.info(
                "Payment status poller cycle completed, waiting %d minutes",
                POLL_INTERVAL_MINUTES,
            )

        except Exception as e:
            logger.exception("Critical error in payment poller: %s", str(e))

        await asyncio.sleep(POLL_INTERVAL_MINUTES * 60)


async def _check_payment_status(payment: Payment, settings: FreedomPaySettings, session: Session):
    """Проверяет статус конкретного платежа в FreedomPay"""
    logger.debug( 
        "Checking payment status: payment_id=%s, order_id=%s, pg_payment_id=%s",
        payment.id,
        payment.order_id,
        payment.pg_payment_id,
    )

    identifier_value = payment.pg_payment_id or payment.order_id

    method_name = "get_status3.php"
    api_status_url = f"{settings.api_url.rstrip('/')}/{method_name}"

    try:
        raw_response, headers, status_code = await get_payment_info(
            merchant_id=settings.merchant_id,
            url=api_status_url,
            payment_id=identifier_value,
            script_name=method_name,
            secret_key=settings.secret,
        )

        logger.debug(
            "Received response from FreedomPay: payment_id=%s, status_code=%s, response_length=%s",
            payment.id,
            status_code,
            len(raw_response),
        )

        payment.last_polled_at = datetime.now(UTC)
        payment.attempts_count = (payment.attempts_count or 0) + 1
        payment.raw_response = raw_response

        old_status = payment.status

        if await _parse_and_update_payment_status(payment, raw_response) and payment.status != old_status:
            history = PaymentStatusHistory(
                payment_id=payment.id,
                status=payment.status,
                notes=f"Auto-updated by poller from {old_status} to {payment.status}",
            )
            session.add(history)
            logger.info(
                "Payment status updated: payment_id=%s, order_id=%s, old_status=%s, new_status=%s",
                payment.id,
                payment.order_id,
                old_status,
                payment.status,
            )

        session.commit()

    except Exception as e:
        logger.exception(
            "Failed to check payment status: payment_id=%s, order_id=%s, error=%s",
            payment.id,
            payment.order_id,
            str(e),
        )
        payment.last_polled_at = datetime.now(UTC)
        payment.attempts_count = (payment.attempts_count or 0) + 1
        session.commit()


async def _parse_and_update_payment_status(payment: Payment, raw_response: str) -> bool:
    """Парсит ответ от FreedomPay и обновляет статус платежа"""
    try:
        root = ET.fromstring(raw_response)
        return _update_payment_from_xml(payment, root)
    except ET.ParseError:
        try:
            response_data = json.loads(raw_response)
            return _update_payment_from_json(payment, response_data)
        except json.JSONDecodeError:
            logger.exception(
                "Failed to parse FreedomPay response: payment_id=%s, response=%s",
                payment.id,
                raw_response[:500],
            )
            return False


def _update_payment_from_xml(payment: Payment, root) -> bool:
    """Обновляет статус платежа из XML ответа согласно документации"""
    pg_status = root.findtext("pg_status")

    if pg_status != "ok":
        error_desc = root.findtext("pg_failure_description") or "Unknown error"
        logger.warning("FreedomPay status request failed: %s", error_desc)
        payment.pg_status_desc = error_desc
        return False

    pg_payment_status = root.findtext("pg_payment_status")

    payment.pg_status_code = pg_payment_status
    payment.pg_status_desc = root.findtext("pg_failure_description") or ""

    if not payment.pg_payment_id:
        payment.pg_payment_id = root.findtext("pg_payment_id")

    payment.pg_payment_method = root.findtext("pg_payment_method") or payment.pg_payment_method

    clearing_amount = root.findtext("pg_clearing_amount")
    if clearing_amount:
        with contextlib.suppress(ValueError, TypeError):
            payment.pg_net_amount = float(clearing_amount)

    payment.pg_card_pan = root.findtext("pg_card_pan") or payment.pg_card_pan
    payment.pg_card_owner = root.findtext("pg_card_name") or payment.pg_card_owner

    payment.pg_user_contact_email = root.findtext("pg_user_email") or payment.pg_user_contact_email
    payment.pg_user_phone = root.findtext("pg_user_phone") or payment.pg_user_phone

    payment_date = root.findtext("pg_payment_date")
    if payment_date:
        with contextlib.suppress(ValueError, TypeError):
            payment.pg_payment_date = datetime.strptime(payment_date, "%Y-%m-%d %H:%M:%S")

    payment.pg_reference = root.findtext("pg_reference") or payment.pg_reference
    payment.pg_auth_code = root.findtext("pg_auth_code") or payment.pg_auth_code

    new_status = _determine_payment_status(pg_payment_status)
    if new_status:
        payment.status = new_status
        return True

    return False


def _update_payment_from_json(payment: Payment, response_data: dict) -> bool:
    """Обновляет статус платежа из JSON ответа"""
    pg_status = response_data.get("pg_status")

    if pg_status != "ok":
        error_desc = response_data.get("pg_failure_description") or "Unknown error"
        logger.warning("FreedomPay status request failed: %s", error_desc)
        payment.pg_status_desc = error_desc
        return False

    pg_payment_status = response_data.get("pg_payment_status")

    payment.pg_status_code = pg_payment_status
    payment.pg_status_desc = response_data.get("pg_failure_description") or ""

    if not payment.pg_payment_id:
        payment.pg_payment_id = response_data.get("pg_payment_id")

    payment.pg_payment_method = response_data.get("pg_payment_method") or payment.pg_payment_method

    clearing_amount = response_data.get("pg_clearing_amount")
    if clearing_amount:
        with contextlib.suppress(ValueError, TypeError):
            payment.pg_net_amount = float(clearing_amount)

    payment.pg_card_pan = response_data.get("pg_card_pan") or payment.pg_card_pan
    payment.pg_card_owner = response_data.get("pg_card_name") or payment.pg_card_owner
    payment.pg_user_contact_email = response_data.get("pg_user_email") or payment.pg_user_contact_email
    payment.pg_user_phone = response_data.get("pg_user_phone") or payment.pg_user_phone

    payment_date = response_data.get("pg_payment_date")
    if payment_date:
        with contextlib.suppress(ValueError, TypeError):
            payment.pg_payment_date = datetime.strptime(payment_date, "%Y-%m-%d %H:%M:%S")

    payment.pg_reference = response_data.get("pg_reference") or payment.pg_reference
    payment.pg_auth_code = response_data.get("pg_auth_code") or payment.pg_auth_code

    new_status = _determine_payment_status(pg_payment_status)
    if new_status:
        payment.status = new_status
        return True

    return False


def _determine_payment_status(pg_payment_status: str):
    """Определяет статус платежа на основе кодов FreedomPay"""
    if not pg_payment_status:
        return None

    pg_payment_status = pg_payment_status.lower()

    if pg_payment_status in ("success", "completed", "approved"):
        return "paid"

    if pg_payment_status in ("failed", "rejected", "cancelled", "error"):
        return "failed"

    if pg_payment_status in ("pending", "in_progress", "created"):
        return None

    return None


def start_poller_on_app(app, freedom_settings: FreedomPaySettings, db_settings: DatabaseSettings):
    """Запускает пулер при старте приложения"""
    logger.info("Starting FreedomPay payment poller")

    try:
        task = asyncio.create_task(poll_pending_payments(freedom_settings, db_settings))
        app.state._fp_poller_task = task
        logger.info("Payment poller started successfully")
    except Exception as e:
        logger.exception("Failed to start payment poller: %s", str(e))


def stop_poller_on_app(app):
    """Останавливает пулер при остановке приложения"""
    logger.info("Stopping FreedomPay payment poller")

    task = getattr(app.state, "_fp_poller_task", None)
    if task and not task.done():
        task.cancel()
        logger.info("Payment poller stopped successfully")
