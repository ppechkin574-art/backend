from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.sql import func

from database import Base


class AppSetting(Base):
    """Key/value row for runtime config editable from the admin panel.

    Use case: knobs that operations needs to flip without a redeploy
    cycle — daily SMS cap, per-IP abuse thresholds, feature toggles.
    Description is shown next to the input in the admin UI so the
    person editing knows what they're changing.
    """

    __tablename__ = "app_settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)
    description = Column(Text, nullable=False, server_default="")

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"AppSetting(key={self.key!r}, value={self.value!r})"
