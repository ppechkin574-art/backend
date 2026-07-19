"""Raw store + dedup for Apple App Store Server Notifications V2.

One row per `notificationUUID`. Apple delivers at-least-once, so the UNIQUE
primary key IS the dedup primitive: the first writer wins and processes the
event; a duplicate delivery fails the insert and is skipped. The raw signed
payload is kept for audit / replay analysis.
"""

from __future__ import annotations

import contextlib

import logging

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from database import Base

logger = logging.getLogger(__name__)


class AppleNotification(Base):
    __tablename__ = "apple_notifications"

    notification_uuid = Column(String(64), primary_key=True)
    notification_type = Column(String(64), nullable=True)
    raw = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return (
            f"<AppleNotification {self.notification_type} "
            f"{self.notification_uuid}>"
        )


def record_notification(session: Session, uuid: str, ntype: str, raw: str) -> bool:
    """Record this notification. Returns True if it's NEW (caller should process
    it), False if a duplicate already exists (caller should skip). Atomic via the
    UNIQUE primary key — concurrent duplicates can't both win.

    Commits its OWN row, so call it at a point where the session is otherwise
    clean (right after decoding, before any processing writes).
    """
    try:
        session.add(
            AppleNotification(
                notification_uuid=uuid, notification_type=ntype, raw=raw
            )
        )
        session.commit()
        return True
    except IntegrityError:
        session.rollback()
        return False
    except Exception:  # noqa: BLE001 — a store hiccup must not drop the event
        logger.exception("[apple_s2s] record_notification failed for uuid=%s", uuid)
        with contextlib.suppress(Exception):
            session.rollback()
        # Fail open: treat as new so the event is still handled (downstream is
        # idempotent). Better a rare double-process than a dropped renewal.
        return True
