from fastapi import HTTPException, status

from events.dtos import EventCreateDTO, EventUpdateDTO
from events.models import Event
from events.repository import EventRepository


class EventService:
    def __init__(self, repo: EventRepository):
        self.repo = repo

    def list_active(self) -> list[Event]:
        return self.repo.list_active()

    def list_all(self) -> list[Event]:
        return self.repo.list_all()

    def get_one(self, event_id: int) -> Event:
        event = self.repo.get(event_id)
        if event is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Событие с id={event_id} не найдено",
            )
        return event

    def create(self, payload: EventCreateDTO) -> Event:
        event = Event(
            type=payload.type,
            badge_text=payload.badge_text,
            title=payload.title,
            prize_text=payload.prize_text,
            subtitle=payload.subtitle,
            secondary_text=payload.secondary_text,
            deadline=payload.deadline,
            button_text=payload.button_text,
            bg_color=payload.bg_color,
            progress_current=payload.progress_current,
            progress_max=payload.progress_max,
            sort_order=payload.sort_order,
            is_active=payload.is_active,
        )
        return self.repo.create(event)

    def update(self, event_id: int, payload: EventUpdateDTO) -> Event:
        event = self.get_one(event_id)
        update_fields = payload.model_dump(exclude_unset=True)
        for field, value in update_fields.items():
            setattr(event, field, value)
        self.repo.db.flush()
        return event

    def delete(self, event_id: int) -> None:
        event = self.get_one(event_id)
        self.repo.delete(event)
