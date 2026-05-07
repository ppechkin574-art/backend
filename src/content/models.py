from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.sql import func

from database import Base


class SubscriptionBenefit(Base):
    """Editable bullet-point shown on the subscription screen ("🔥 Входят
    в вашу подписку").  Admins manage these via the admin panel; the
    mobile app fetches the active list and renders title + description
    in the user's locale (RU default, KZ when device locale is kk*).

    Hardcoded defaults that used to live in
    `lib/features/profile/presentation/screens/subscription_profile_screen.dart`
    were seeded into this table by the initial migration so the UI never
    shows an empty list right after deploy.
    """

    __tablename__ = "subscription_benefits"

    id = Column(Integer, primary_key=True)
    position = Column(Integer, nullable=False, default=0, index=True)

    # Russian copy is required (default locale).  Kazakh copy is
    # required at the column level so admin UI forces translators to
    # fill it in; the mobile app falls back to RU if KZ is empty.
    title_ru = Column(String(200), nullable=False)
    title_kz = Column(String(200), nullable=False)
    description_ru = Column(Text, nullable=False)
    description_kz = Column(Text, nullable=False)

    is_active = Column(Boolean, nullable=False, default=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_subscription_benefits_active_position", "is_active", "position"),
    )

    def __repr__(self) -> str:
        return f"SubscriptionBenefit(id={self.id}, position={self.position}, title_ru={self.title_ru!r})"
