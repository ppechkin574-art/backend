from sqlalchemy import select
from sqlalchemy.orm import Session

from events.models import Event


class EventRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_all(self) -> list[Event]:
        return list(
            self.db.scalars(
                select(Event).order_by(Event.sort_order, Event.id)
            ).all()
        )

    def list_active(self) -> list[Event]:
        return list(
            self.db.scalars(
                select(Event)
                .where(Event.is_active.is_(True))
                .order_by(Event.sort_order, Event.id)
            ).all()
        )

    def get(self, event_id: int) -> Event | None:
        return self.db.get(Event, event_id)

    def create(self, event: Event) -> Event:
        self.db.add(event)
        self.db.flush()
        return event

    def delete(self, event: Event) -> None:
        self.db.delete(event)
        self.db.flush()
