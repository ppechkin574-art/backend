# from datetime import UTC, datetime, timedelta

# from models.subscription import (
#     Subscription,
#     SubscriptionHistory,
#     SubscriptionStatus,
# )
# from sqlalchemy import and_
# from sqlalchemy.orm import Session

# from common.enums import PlanType


# class SubscriptionRepository:
#     def __init__(self, session: Session):
#         self.session = session

#     # def create_subscription(
#     #     self,
#     #     user_id: str,
#     #     plan: PlanType,
#     #     months: int = 1,
#     #     payment_id: int | None = None,
#     #     promocode_id: int | None = None,
#     # ) -> Subscription:
#     #     """Создать новую подписку"""
#     #     now = datetime.now(UTC)

#     #     subscription = Subscription(
#     #         user_id=user_id,
#     #         plan=plan.value,
#     #         status=SubscriptionStatus.PENDING.value,
#     #         started_at=now if payment_id else None,
#     #         expires_at=now + timedelta(days=30 * months) if payment_id else None,
#     #         payment_id=payment_id,
#     #         promocode_id=promocode_id,
#     #         auto_renew=1,
#     #     )

#     #     self.session.add(subscription)
#     #     self.session.flush()

#     #     history = SubscriptionHistory(
#     #         subscription_id=subscription.id,
#     #         new_status=subscription.status,
#     #         event_type="created",
#     #         history_metadata={
#     #             "plan": plan.value,
#     #             "months": months,
#     #             "payment_id": payment_id,
#     #             "promocode_id": promocode_id,
#     #         },
#     #     )
#     #     self.session.add(history)

#     #     return subscription

#     # def get_active_subscription(self, user_id: str) -> Subscription | None:
#     #     """Получить активную подписку пользователя"""
#     #     now = datetime.now(UTC)

#     #     return (
#     #         self.session.query(Subscription)
#     #         .filter(
#     #             and_(
#     #                 Subscription.user_id == user_id,
#     #                 Subscription.status == SubscriptionStatus.ACTIVE.value,
#     #                 Subscription.expires_at > now,
#     #             )
#     #         )
#     #         .first()
#     #     )

#     # def get_pending_subscription(self, user_id: str) -> Subscription | None:
#     #     """Получить подписку в статусе pending (ожидает оплаты)"""
#     #     return (
#     #         self.session.query(Subscription)
#     #         .filter(
#     #             and_(
#     #                 Subscription.user_id == user_id,
#     #                 Subscription.status == SubscriptionStatus.PENDING.value,
#     #             )
#     #         )
#     #         .first()
#     #     )

#     def activate_subscription(self, subscription_id: int) -> Subscription:
#         """Активировать подписку после успешной оплаты"""
#         subscription = self.session.query(Subscription).get(subscription_id)
#         if not subscription:
#             raise ValueError(f"Subscription {subscription_id} not found")

#         old_status = subscription.status
#         now = datetime.now(UTC)

#         if not subscription.started_at:
#             subscription.started_at = now

#         if not subscription.expires_at:
#             subscription.expires_at = now + timedelta(days=30)

#         subscription.status = SubscriptionStatus.ACTIVE.value
#         subscription.updated_at = now

#         history = SubscriptionHistory(
#             subscription_id=subscription.id,
#             old_status=old_status,
#             new_status=subscription.status,
#             event_type="activated",
#             history_metadata={"activated_at": now.isoformat()},
#         )
#         self.session.add(history)

#         return subscription

#     # def cancel_subscription(self, subscription_id: int) -> Subscription:
#     #     """Отменить подписку"""
#     #     subscription = self.session.query(Subscription).get(subscription_id)
#     #     if not subscription:
#     #         raise ValueError(f"Subscription {subscription_id} not found")

#     #     old_status = subscription.status
#     #     now = datetime.now(UTC)

#     #     subscription.status = SubscriptionStatus.CANCELLED.value
#     #     subscription.cancelled_at = now
#     #     subscription.auto_renew = 0
#     #     subscription.updated_at = now

#     #     history = SubscriptionHistory(
#     #         subscription_id=subscription.id,
#     #         old_status=old_status,
#     #         new_status=subscription.status,
#     #         event_type="cancelled",
#     #         history_metadata={"cancelled_at": now.isoformat()},
#     #     )
#     #     self.session.add(history)

#     #     return subscription

#     # def renew_subscription(self, subscription_id: int, months: int = 1) -> Subscription:
#     #     """Продлить подписку"""
#     #     subscription = self.session.query(Subscription).get(subscription_id)
#     #     if not subscription:
#     #         raise ValueError(f"Subscription {subscription_id} not found")

#     #     now = datetime.now(UTC)

#     #     if subscription.expires_at and subscription.expires_at < now:
#     #         subscription.expires_at = now + timedelta(days=30 * months)
#     #     elif subscription.expires_at:
#     #         subscription.expires_at = subscription.expires_at + timedelta(days=30 * months)
#     #     else:
#     #         subscription.expires_at = now + timedelta(days=30 * months)

#     #     subscription.updated_at = now

#     #     history = SubscriptionHistory(
#     #         subscription_id=subscription.id,
#     #         old_status=subscription.status,
#     #         new_status=subscription.status,
#     #         event_type="renewed",
#     #         history_metadata={
#     #             "months": months,
#     #             "new_expires_at": subscription.expires_at.isoformat(),
#     #         },
#     #     )
#     #     self.session.add(history)

#     #     return subscription

#     # def expire_subscription(self, subscription_id: int) -> Subscription:
#     #     """Пометить подписку как истекшую"""
#     #     subscription = self.session.query(Subscription).get(subscription_id)
#     #     if not subscription:
#     #         raise ValueError(f"Subscription {subscription_id} not found")

#     #     old_status = subscription.status
#     #     now = datetime.now(UTC)

#     #     subscription.status = SubscriptionStatus.EXPIRED.value
#     #     subscription.updated_at = now

#     #     history = SubscriptionHistory(
#     #         subscription_id=subscription.id,
#     #         old_status=old_status,
#     #         new_status=subscription.status,
#     #         event_type="expired",
#     #         history_metadata={"expired_at": now.isoformat()},
#     #     )
#     #     self.session.add(history)

#     #     return subscription

#     # def get_user_subscriptions(self, user_id: str, limit: int = 10) -> list[Subscription]:
#     #     """Получить историю подписок пользователя"""
#     #     return (
#     #         self.session.query(Subscription)
#     #         .filter(Subscription.user_id == user_id)
#     #         .order_by(Subscription.created_at.desc())
#     #         .limit(limit)
#     #         .all()
#     #     )

#     # def update_keycloak_user(self, user_id: str, plan: PlanType, expires_at: datetime | None = None):
#     #     """Обновить пользователя в Keycloak (синхронная версия)"""
#     #     # Этот метод будет вызываться из PaymentService для обновления Keycloak
#     #     # Нужно интегрировать с существующей системой обновления пользователей
#     #     pass
