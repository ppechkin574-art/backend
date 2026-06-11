import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from quiz.daily_notification_dtos import DailyNotificationTemplateUpdateDTO
from quiz.models.daily_tests import DailyNotificationTemplate

logger = logging.getLogger(__name__)


class DailyNotificationTemplateService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self) -> DailyNotificationTemplate:
        template = self._session.get(DailyNotificationTemplate, 1)
        if template is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Daily notification template not initialized (should be seeded by migration)",
            )
        return template

    def update(self, payload: DailyNotificationTemplateUpdateDTO) -> DailyNotificationTemplate:
        template = self.get()
        if payload.enabled is not None:
            template.enabled = payload.enabled
        if payload.title is not None:
            template.title = payload.title
        if payload.body is not None:
            template.body = payload.body
        if payload.hour is not None:
            template.hour = payload.hour
        if payload.minute is not None:
            template.minute = payload.minute
        if payload.timezone is not None:
            template.timezone = payload.timezone
        self._session.flush()
        return template
