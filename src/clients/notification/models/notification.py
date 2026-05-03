from datetime import UTC, datetime

from sqlalchemy import JSON, Column, DateTime, Index, Integer, String, Text

from database import Base


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String(50), nullable=False)
    platform = Column(String(50), nullable=False)
    to_address = Column(String(255), nullable=False)
    from_address = Column(String(255), nullable=True)
    subject = Column(String(500), nullable=True)
    message = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, default="pending")
    error_message = Column(Text, nullable=True)
    metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.now(UTC).isoformat())
    sent_at = Column(DateTime, default=datetime.now(UTC).isoformat())

    __table_args__ = (
        Index("ix_notification_logs_type", "type"),
        Index("ix_notification_logs_platform", "platform"),
        Index("ix_notification_logs_created_at", "created_at"),
        Index("ix_notification_logs_to_address", "to_address"),
    )
