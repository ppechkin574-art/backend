import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import defusedxml.ElementTree as ET
from fastapi import HTTPException
from sqlalchemy.orm import Session

from auth.dtos.users import UserDTO
from auth.services import AuthServiceInterface
from clients.freedom_pay.client import make_order_id, post_to_fp
from clients.freedom_pay.settings import FreedomPaySettings
from common.enums import PlanType
from payments.models import Payment, PaymentStatusHistory
from subscription.models import Subscription, SubscriptionHistory, SubscriptionStatus
from subscription.plan_service import SubscriptionPlanService
from subscription.service import SubscriptionService

logger = logging.getLogger(__name__)


class PaymentService:
    def __init__(
        self,
        payment_settings: FreedomPaySettings,
        db_session: Session,
        user: UserDTO,
        auth_service: AuthServiceInterface,
        subscription_service: SubscriptionService,
        subscription_plan_service: SubscriptionPlanService | None = None,
    ):
        self.freedom_pay_settings = payment_settings
        self.session = db_session
        self.user = user
        self.auth_service = auth_service
        self.subscription_service = subscription_service
        self.subscription_plan_service = subscription_plan_service

    async def create_payment(
        self,
        amount: Decimal,
        pg_card_token: str | None = None,
        description: str | None = None,
    ) -> Payment:
        """Создание обычного платежа (не для подписки)"""
        logger.info("Creating payment for user: %s, amount: %s", self.user.id, amount)
        min_amount = 1000
        if amount < min_amount:
            logger.warning("Payment amount below minimum: %s < %s", amount, min_amount)
            raise HTTPException(status_code=400, detail=f"Minimum amount is {min_amount}")

        order_id = make_order_id(self.session)
        method_name = "init_payment"

        logger.debug("Generated order_id: %s for user_id: %s", order_id, self.user.id)

        session = self.session
        p = Payment(
            order_id=order_id,
            amount=amount,
            user_id=str(self.user.id),
            status="created",
        )
        session.add(p)
        session.commit()
        session.refresh(p)
        logger.info(
            "Payment record created in database: payment_id=%s, order_id=%s",
            p.id,
            order_id,
        )

        # Pass user phone and email so FreedomPay can hide / pre-validate those
        # fields on its customer page. We strip None / empty / 'None' / synthetic
        # internal-only emails before sending.
        user_phone = getattr(self.user, "phone", None)
        user_email = getattr(self.user, "email", None)

        # FreedomPay form expects phone in 11-digit format without '+'
        clean_phone = None
        if user_phone:
            clean_phone = "".join(c for c in str(user_phone) if c.isdigit())
            if not clean_phone:
                clean_phone = None

        clean_email = str(user_email).strip() if user_email else None
        if clean_email and (clean_email.endswith(".internal") or "@aima.internal" in clean_email):
            clean_email = None

        params = {k: v for k, v in {
            "pg_merchant_id": self.freedom_pay_settings.merchant_id,
            "pg_order_id": order_id,
            "pg_amount": str(amount),
            "pg_description": description if description else f"Order {order_id}",
            "pg_testing_mode": "1",
            "pg_result_url": f"{self.freedom_pay_settings.callback_url}/fp/result_notify",
            "pg_success_url": f"{self.freedom_pay_settings.callback_url}/payment/success",
            "pg_failure_url": f"{self.freedom_pay_settings.callback_url}/payment/failed",
            "pg_user_id": f"{str(self.user.id)}",
            "pg_user_phone": clean_phone,
            "pg_user_contact_email": clean_email,
            "pg_user_ip": "127.0.0.1",
            # Hide user form fields that we already provide
            "pg_skip_user_form": "1",
        }.items() if v is not None and str(v).strip() != "" and str(v).strip().lower() != "none"}

        if pg_card_token:
            params["pg_card_token"] = pg_card_token
            logger.debug("Card token provided for payment: order_id=%s", order_id)

        FP_CREATE_URL = f"{self.freedom_pay_settings.api_url.rstrip('/')}/{method_name}"

        try:
            logger.info(
                "Sending payment request to FreedomPay: order_id=%s, url=%s",
                order_id,
                FP_CREATE_URL,
            )

            raw_text, _, status = await post_to_fp(FP_CREATE_URL, params, method_name, self.freedom_pay_settings.secret)

            p.raw_request = json.dumps(params, default=str, ensure_ascii=False)
            p.raw_response = raw_text

            logger.debug(
                "Received response from FreedomPay: status=%s, response_length=%s",
                status,
                len(raw_text),
            )

            try:
                root = ET.fromstring(raw_text)
                pg_status = root.findtext("pg_status")
                p.pg_status_code = pg_status
                p.pg_status_desc = root.findtext("pg_status_description") or ""

                if pg_status == "ok":
                    p.pg_payment_id = root.findtext("pg_payment_id")
                    p.pg_redirect_url = root.findtext("pg_redirect_url")
                    p.status = "pending"
                    logger.info(
                        "Payment initiated successfully: order_id=%s, payment_id=%s, status=%s",
                        order_id,
                        p.pg_payment_id,
                        p.status,
                    )
                else:
                    p.status = "failed"
                    logger.exception(
                        "Payment initiation failed: order_id=%s, pg_status=%s, description=%s",
                        order_id,
                        pg_status,
                        p.pg_status_desc,
                    )
            except ET.ParseError:
                try:
                    logger.warning("Received non-XML response from FreedomPay, trying JSON parsing")
                    response_data = json.loads(raw_text)
                    p.pg_payment_id = response_data.get("pg_payment_id")
                    p.pg_status_code = response_data.get("pg_status_code")
                    p.pg_status_desc = response_data.get("pg_status_description")
                    if response_data.get("pg_status") == "ok":
                        p.pg_redirect_url = response_data.get("pg_redirect_url")
                        p.status = "pending"
                        logger.info("Payment initiated via JSON response: order_id=%s", order_id)
                    else:
                        p.status = "failed"
                        logger.exception("Payment failed via JSON response: order_id=%s", order_id)
                except Exception as json_parse_error:
                    p.status = "failed"
                    p.pg_status_desc = "Invalid response format"
                    logger.exception(
                        "Failed to parse FreedomPay response: order_id=%s, error=%s",
                        order_id,
                        str(json_parse_error),
                    )

            session.add(p)
            session.commit()
            session.refresh(p)

            history = PaymentStatusHistory(payment_id=p.id, status=p.status)
            session.add(history)
            session.commit()

            logger.info(
                "Payment process completed: order_id=%s, final_status=%s",
                order_id,
                p.status,
            )

            return p

        except Exception as e:
            logger.exception(
                "Unexpected error during payment creation: order_id=%s, error=%s",
                order_id,
                str(e),
            )
            session.rollback()
            raise e

    async def create_subscription_payment(
        self,
        subscription_plan_id: int,
        months: int = 1,
        pg_card_token: str | None = None,
    ) -> Payment:
        """Создание платежа для подписки"""

        plan = self.subscription_plan_service.get_plan_by_id(subscription_plan_id)

        if not plan.is_active:
            raise HTTPException(status_code=400, detail="This plan is not available for purchase")

        amount = self.subscription_plan_service.calculate_price_for_months(plan, months)

        description = f"Оплата подписки {plan.name} на {months} мес."

        payment = await self.create_payment(
            amount=amount,
            pg_card_token=pg_card_token,
            description=description,
        )

        payment.is_subscription_payment = True
        payment.subscription_plan = plan.plan_type

        subscription = Subscription(
            user_id=str(self.user.id),
            subscription_plan_id=plan.id,
            plan=plan.plan_type,
            status=SubscriptionStatus.PENDING.value,
            payment_id=payment.id,
        )

        self.session.add(subscription)
        self.session.add(payment)
        self.session.commit()

        return payment

    def get_subscription_plans(self) -> list[dict[str, Any]]:
        """Получение списка доступных планов из БД"""
        plans = self.subscription_plan_service.get_available_plans()
        return [self.subscription_plan_service.get_plan_features_summary(plan) for plan in plans]

    async def activate_subscription_after_payment(self, payment_id: int) -> Subscription:
        """Активация подписки после успешного платежа"""
        payment = (
            self.session.query(Payment)
            .filter(
                Payment.id == payment_id,
                Payment.status == "paid",
                Payment.is_subscription_payment,
                Payment.subscription_plan.isnot(None),
            )
            .first()
        )

        if not payment:
            raise HTTPException(
                status_code=404,
                detail="Payment not found or not eligible for subscription",
            )

        subscription = self.session.query(Subscription).filter(Subscription.payment_id == payment_id).first()

        if not subscription:
            subscription = Subscription(
                user_id=payment.user_id,
                plan=payment.subscription_plan,
                status=SubscriptionStatus.PENDING.value,
                payment_id=payment.id,
            )

        price_per_month = Decimal("3900.00")
        months = int(payment.amount / price_per_month)

        return await self._activate_subscription(
            subscription=subscription,
            plan_type=PlanType(payment.subscription_plan),
            months=months,
        )

    async def _activate_subscription(
        self, subscription: Subscription, plan_type: PlanType, months: int = 1
    ) -> Subscription:
        """Активирует подписку в базе и Keycloak"""
        old_status = subscription.status

        now = datetime.now(UTC)
        expires_at = now + timedelta(days=30 * months)

        subscription.status = SubscriptionStatus.ACTIVE.value
        subscription.started_at = now
        subscription.expires_at = expires_at
        subscription.updated_at = now

        history = SubscriptionHistory(
            subscription_id=subscription.id,
            old_status=old_status,
            new_status=subscription.status,
            event_type="activated",
            history_metadata={
                "activated_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "months": months,
            },
        )

        self.session.add(history)
        self.session.commit()

        if self.subscription_service:
            try:
                user = await self.auth_service.get_user_by_id(subscription.user_id)
                if user:
                    await self.subscription_service.activate_subscription(user=user, plan=plan_type, months=months)
                    logger.info(
                        "Subscription activated in Keycloak for user %s",
                        subscription.user_id,
                    )
            except Exception as e:
                logger.exception("Failed to activate subscription in Keycloak: %s", e)

        return subscription

    # def get_user_active_subscription(self, user_id: str) -> Subscription | None:
    #     """Получение активной подписки пользователя"""
    #     return (
    #         self.session.query(Subscription)
    #         .filter(
    #             Subscription.user_id == user_id,
    #             Subscription.status == SubscriptionStatus.ACTIVE.value,
    #             Subscription.expires_at > datetime.now(UTC),
    #         )
    #         .first()
    #     )
