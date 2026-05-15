from sqlalchemy.orm import Session

from app_config.models import AppSetting


class AppSettingsRepository:
    """Thin DB wrapper for `app_settings`. Mirrors the style of
    `SubscriptionBenefitRepository` so the mental model is consistent
    across content admin tables."""

    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[AppSetting]:
        """Every row, ordered by key for stable admin-UI rendering."""
        return self.session.query(AppSetting).order_by(AppSetting.key.asc()).all()

    def get(self, key: str) -> AppSetting | None:
        return self.session.query(AppSetting).filter(AppSetting.key == key).first()

    def update_value(self, key: str, value: str) -> AppSetting | None:
        row = self.get(key)
        if row is None:
            return None
        row.value = value
        self.session.commit()
        self.session.refresh(row)
        return row
