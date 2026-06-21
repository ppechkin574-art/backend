"""Raw store + dedup for Google Play Real-time Developer Notifications (RTDN).

One row per Pub/Sub `messageId`. Google/Pub/Sub deliver at-least-once (a push may
be redelivered), so the UNIQUE primary key IS the dedup primitive: the first
writer wins and processes the event; a duplicate delivery fails the insert and is
skipped. The raw Pub/Sub envelope is kept for audit / replay analysis.

Mirrors `apple_notification.py` (App Store Server Notifications V2).
"""

from __future__ import annotations

import logging

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from database import Base

logger = logging.getLogger(__name__)


class GoogleNotification(Base):
    __tablename__ = "google_notifications"

    message_id = Column(String(128), primary_key=True)
    notification_type = Column(String(64), nullable=True)
    raw = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<GoogleNotification {self.notification_type} {self.message_id}>"


def record_google_notification(
    session: Session, message_id: str, ntype: str, raw: str
) -> bool:
    """Record this RTDN. Returns True if it's NEW (caller should process it),
    False if a duplicate already exists (caller should skip). Atomic via the
    UNIQUE primary key — concurrent redeliveries can't both win.

    Commits its OWN row, so call it at a point where the session is otherwise
    clean (right after decoding, before any processing writes).
    """
    try:
        session.add(
            GoogleNotification(
                message_id=message_id, notification_type=ntype, raw=raw
            )
        )
        session.commit()
        return True
    except IntegrityError:
        session.rollback()
        return False
    except Exception:  # noqa: BLE001 — a store hiccup must not drop the event
        logger.exception(
            "[google_rtdn] record_google_notification failed for message_id=%s",
            message_id,
        )
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
        # Fail open: treat as new so the event is still handled (downstream is
        # idempotent). Better a rare double-process than a dropped renewal.
        return True
