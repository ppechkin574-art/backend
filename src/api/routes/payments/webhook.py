import contextlib
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from api.dependencies import (
    get_db_session,
    get_identity_provider_client_keycloak,
    get_payment_settings,
)
from api.routes.payments.websocket.manager import manager
from clients.freedom_pay.client import make_pg_sig, verify_pg_sig
from clients.freedom_pay.settings import FreedomPaySettings
from clients.identity_provider.client import IdentityProviderClientInterface
from common.enums import PlanType, SubscriptionStatus
from payments.models import Payment, PaymentStatusHistory
from subscription.models import (
    Subscription,
    SubscriptionHistory,
    SubscriptionPlan,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fp", tags=["User - Payments"])


@router.post("/result_notify")
async def result_notify(
    request: Request,
    settings: FreedomPaySettings = Depends(get_payment_settings),
    session: Session = Depends(get_db_session),
    identity_provider_client: IdentityProviderClientInterface = Depends(get_identity_provider_client_keycloak),
):
    form = await request.form()
    data = dict(form)
    incoming_sig = data.get("pg_sig", "")

    method_name = "result_notify"

    logger.info("Received payment webhook notification for order: %s", data.get("pg_order_id"))
    logger.debug("Webhook data: %s", data)

    if not verify_pg_sig(data, method_name, settings.secret, incoming_sig):
        root = Element("response")
        SubElement(root, "pg_status").text = "error"
        SubElement(root, "pg_description").text = "bad signature"
        SubElement(root, "pg_salt").text = data.get("pg_salt", "")

        response_data = {
            "pg_status": "error",
            "pg_description": "bad signature",
            "pg_salt": data.get("pg_salt", ""),
        }

        SubElement(root, "pg_sig").text = make_pg_sig(response_data, method_name, settings.secret)

        return Response(content=tostring(root), media_type="application/xml", status_code=400)

    order_id = data.get("pg_order_id")
    payment = session.query(Payment).filter(Payment.order_id == order_id).first()

    if payment:
        # Idempotency: если уже обработан — вернуть success без повторной активации
        if payment.status == "paid":
            logger.info("Payment already processed (idempotent), skipping: %s", order_id)
            return _create_success_response(data, method_name, settings.secret)

        old_status = payment.status
        logger.info(
            "Processing payment update for order: %s, current status: %s",
            order_id,
            old_status,
        )

        payment.pg_payment_id = data.get("pg_payment_id")
        payment.pg_reference = data.get("pg_reference") or payment.pg_reference
        payment.pg_auth_code = data.get("pg_auth_code") or payment.pg_auth_code
        payment.pg_payment_date = data.get("pg_payment_date") or payment.pg_payment_date

        payment.pg_card_pan = data.get("pg_card_pan") or payment.pg_card_pan
        payment.pg_card_brand = data.get("pg_card_brand") or payment.pg_card_brand
        payment.pg_card_exp = data.get("pg_card_exp") or payment.pg_card_exp
        payment.pg_card_owner = data.get("pg_card_owner") or payment.pg_card_owner

        # amounts / other info
        payment.pg_payment_method = data.get("pg_payment_method")
        with contextlib.suppress(Exception):
            payment.pg_net_amount = data.get("pg_net_amount") if data.get("pg_net_amount") else payment.pg_net_amount
        with contextlib.suppress(Exception):
            payment.pg_ps_amount = data.get("pg_ps_amount") if data.get("pg_ps_amount") else payment.pg_ps_amount
        payment.pg_ps_currency = data.get("pg_ps_currency") or payment.pg_ps_currency
        with contextlib.suppress(Exception):
            payment.pg_ps_full_amount = (
                int(data.get("pg_ps_full_amount")) if data.get("pg_ps_full_amount") else payment.pg_ps_full_amount
            )

        payment.pg_result = (
            int(data.get("pg_result"))
            if data.get("pg_result") and str(data.get("pg_result")).isdigit()
            else payment.pg_result
        )
        payment.pg_status_code = data.get("pg_status") or data.get("pg_result") or payment.pg_status_code
        payment.pg_status_desc = (
            data.get("pg_failure_description")
            or data.get("pg_error_description")
            or data.get("pg_description")
            or payment.pg_status_desc
        )

        payment.pg_user_contact_email = data.get("pg_user_contact_email") or payment.pg_user_contact_email
        payment.pg_user_ip = data.get("pg_user_ip") or payment.pg_user_ip
        payment.pg_user_phone = data.get("pg_user_phone") or payment.pg_user_phone

        pg_status = (data.get("pg_status") or data.get("pg_result") or "").lower()
        if pg_status in ("ok", "success", "1"):
            payment.status = "paid"
            logger.info("Payment marked as paid for order: %s", order_id)
        else:
            payment.status = "failed"
            logger.warning("Payment marked as failed for order: %s", order_id)

        session.add(payment)
        session.commit()

        if old_status != payment.status:
            history = PaymentStatusHistory(payment_id=payment.id, status=payment.status)
            session.add(history)
            session.commit()
            logger.info(
                "Payment status changed from %s to %s for order: %s",
                old_status,
                payment.status,
                order_id,
            )

            try:
                await manager.broadcast_to_order(
                    {
                        "type": "payment_status_updated",
                        "order_id": order_id,
                        "new_status": payment.status,
                        "old_status": old_status,
                        "timestamp": (payment.updated_at.isoformat() if payment.updated_at else None),
                    },
                    order_id,
                )
            except Exception as ws_error:
                logger.exception("WebSocket broadcast failed for order %s: %s", order_id, ws_error)

    else:
        logger.warning("Payment not found for order ID: %s", order_id)
        return _create_success_response(data, method_name, settings.secret)

    if payment and payment.status == "paid" and payment.is_subscription_payment:
        logger.info("Processing subscription activation for payment: %s", payment.id)

        try:
            # Определяем длительность из плана в БД
            raw_plan = (payment.subscription_plan or "").strip()
            plan_type = next(
                (pt for pt in PlanType if pt.value.upper() == raw_plan.upper()),
                None,
            )
            duration_days = 30  # fallback
            if plan_type is not None:
                db_plan = session.query(SubscriptionPlan).filter(
                    SubscriptionPlan.plan_type == plan_type.value
                ).first()
                if db_plan and db_plan.duration_days:
                    duration_days = db_plan.duration_days

            expires_at = datetime.now(UTC) + timedelta(days=duration_days)

            # Находим или создаем подписку
            subscription = session.query(Subscription).filter(Subscription.payment_id == payment.id).first()

            if not subscription:
                subscription = Subscription(
                    user_id=payment.user_id,
                    plan=raw_plan or PlanType.PRO.value,
                    status=SubscriptionStatus.ACTIVE.value,
                    payment_id=payment.id,
                    started_at=datetime.now(UTC),
                    expires_at=expires_at,
                )
                session.add(subscription)
            else:
                subscription.status = SubscriptionStatus.ACTIVE.value
                subscription.started_at = datetime.now(UTC)
                subscription.expires_at = expires_at

            # Записываем в историю подписки
            history = SubscriptionHistory(
                subscription_id=subscription.id,
                old_status=SubscriptionStatus.PENDING.value,
                new_status=subscription.status,
                event_type="activated",
                history_metadata={
                    "activated_at": datetime.now(UTC).isoformat(),
                    "payment_id": payment.id,
                },
            )
            session.add(history)

            session.commit()

            # Обновляем Keycloak через IdentityProviderClient
            try:
                raw_plan = (subscription.plan or "").strip()
                plan_type = next(
                    (pt for pt in PlanType if pt.value.upper() == raw_plan.upper()),
                    None,
                )
                if plan_type is None:
                    raise ValueError(f"Unknown plan: {raw_plan}")

                identity_provider_client.update_user_subscription(
                    user_id=UUID(payment.user_id),
                    plan=plan_type,
                    expires_at=expires_at,
                    subscription_cancelled=False,
                )

                logger.info("Keycloak updated successfully for user %s", payment.user_id)

            except Exception as e:
                logger.exception("Failed to update Keycloak: %s", e)
                # Не прерываем процесс, так как подписка в нашей базе уже активирована

            logger.info(
                "Subscription activated: %s for user %s",
                subscription.id,
                payment.user_id,
            )

        except Exception as e:
            logger.exception("Failed to activate subscription: %s", e)
            session.rollback()
            # Не возвращаем ошибку, чтобы FreedomPay не повторял запрос

    return _create_success_response(data, method_name, settings.secret)


def _create_success_response(data: dict, method_name: str, secret_key: str) -> Response:
    """Создает успешный ответ для FreedomPay"""
    root = Element("response")
    SubElement(root, "pg_status").text = "ok"
    SubElement(root, "pg_description").text = "accepted"
    SubElement(root, "pg_salt").text = data.get("pg_salt", "")

    response_data = {
        "pg_status": "ok",
        "pg_description": "accepted",
        "pg_salt": data.get("pg_salt", ""),
    }
    SubElement(root, "pg_sig").text = make_pg_sig(response_data, method_name, secret_key)

    logger.info("Webhook processed successfully")

    return Response(content=tostring(root), media_type="application/xml")


async def handle_subscription_activation(payment_id: int, db: Session):
    """Активирует подписку после успешной оплаты"""
    try:
        from config import settings

        from auth.services import AuthService
        from payments.services import PaymentService

        # Получаем платеж
        payment = db.query(Payment).filter(Payment.id == payment_id).first()
        if not payment:
            logger.exception("Payment %s not found", payment_id)
            return

        # Создаем сервисы для активации подписки
        # Нужно получить пользователя и настроить зависимости
        # Это упрощенный пример - в реальности нужно правильно настроить DI

        # Для активации в нашей базе данных
        payment_service = PaymentService(
            payment_settings=settings.freedom_pay,
            db_session=db,
            user=None,  # Будет получен из платежа
            auth_service=AuthService(),
        )

        # Активируем подписку в нашей базе
        subscription = await payment_service.activate_subscription(payment.id)
        logger.info("Subscription activated: %s", subscription.id)

    except Exception as e:
        logger.exception("Failed to activate subscription: %s", str(e))
