"""Admin CRUD for events (banners + event cards on Главная screen).

Endpoints (all protected by allow_only_admins):
- GET    /admin/events           — list all (active + inactive)
- POST   /admin/events           — create
- GET    /admin/events/{id}      — get one
- PATCH  /admin/events/{id}      — partial update
- DELETE /admin/events/{id}      — hard delete
"""

from fastapi import APIRouter, Depends

from api.dependencies import allow_only_admins, get_event_service
from events.dtos import EventCreateDTO, EventDTO, EventUpdateDTO
from events.service import EventService

router = APIRouter(
    prefix="/admin/events",
    tags=["admin"],
    dependencies=[Depends(allow_only_admins)],
)


@router.get("", response_model=list[EventDTO])
def list_events(service: EventService = Depends(get_event_service)):
    return [EventDTO.model_validate(e) for e in service.list_all()]


@router.post("", response_model=EventDTO, status_code=201)
def create_event(
    body: EventCreateDTO,
    service: EventService = Depends(get_event_service),
):
    event = service.create(body)
    service.repo.db.commit()
    return EventDTO.model_validate(event)


@router.get("/{event_id}", response_model=EventDTO)
def get_event(
    event_id: int,
    service: EventService = Depends(get_event_service),
):
    return EventDTO.model_validate(service.get_one(event_id))


@router.patch("/{event_id}", response_model=EventDTO)
def update_event(
    event_id: int,
    body: EventUpdateDTO,
    service: EventService = Depends(get_event_service),
):
    event = service.update(event_id, body)
    service.repo.db.commit()
    return EventDTO.model_validate(event)


@router.delete("/{event_id}", status_code=204)
def delete_event(
    event_id: int,
    service: EventService = Depends(get_event_service),
):
    service.delete(event_id)
    service.repo.db.commit()
