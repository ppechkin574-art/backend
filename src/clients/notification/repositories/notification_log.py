# import logging
# from datetime import UTC, datetime, timedelta
# from typing import Any

# from sqlalchemy.orm import Session

# from clients.notification.models.notification import NotificationLog

# logger = logging.getLogger(__name__)


# class NotificationLogRepository:
#     def __init__(self, db_session: Session):
#         self.db_session = db_session

#     def log_notification(
#         self,
#         notification_type: str,
#         platform: str,
#         to_address: str,
#         message: str,
#         from_address: str | None = None,
#         subject: str | None = None,
#         status: str = "sent",
#         error_message: str | None = None,
#         metadata: dict[str, Any] | None = None,
#     ) -> NotificationLog:
#         try:
#             notification_log = NotificationLog(
#                 type=notification_type,
#                 platform=platform,
#                 to_address=to_address,
#                 from_address=from_address,
#                 subject=subject,
#                 message=message,
#                 status=status,
#                 error_message=error_message,
#                 metadata=metadata or {},
#                 created_at=datetime.now(UTC).isoformat(),
#                 sent_at=datetime.now(UTC).isoformat(),
#             )

#             self.db_session.add(notification_log)
#             self.db_session.commit()

#             logger.info("Notification logged: %s via %s to %s", notification_type, platform, to_address)
#             return notification_log

#         except Exception as e:
#             self.db_session.rollback()
#             logger.exception("Failed to log notification: %s", str(e))
#             raise

#     def get_notifications_by_user(self, to_address: str, limit: int = 100) -> list[NotificationLog]:
#         """Получает историю уведомлений для пользователя"""
#         return (
#             self.db_session.query(NotificationLog)
#             .filter(NotificationLog.to_address == to_address)
#             .order_by(NotificationLog.created_at.desc())
#             .limit(limit)
#             .all()
#         )

#     def get_notifications_by_type(
#         self, notification_type: str, platform: str | None = None, days: int = 30
#     ) -> list[NotificationLog]:
#         """Получает уведомления по типу за указанный период"""
#         query = self.db_session.query(NotificationLog).filter(
#             NotificationLog.type == notification_type,
#             NotificationLog.created_at >= datetime.now(UTC).isoformat() - timedelta(days=days),
#         )

#         if platform:
#             query = query.filter(NotificationLog.platform == platform)

#         return query.order_by(NotificationLog.created_at.desc()).all()
