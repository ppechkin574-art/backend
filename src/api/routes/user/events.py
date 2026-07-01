"""Public read-only endpoint for events (banners + cards on Главная screen).

App fetches this on HomeMainScreen mount — no auth required.
"""

from fastapi import APIRouter, Depends

from api.dependencies import get_event_service
from events.dtos import EventDTO
from events.service import EventService

router = APIRouter(prefix="/events", tags=["user"])


@router.get("", response_model=list[EventDTO])
def list_active_events(service: EventService = Depends(get_event_service)):
    return [EventDTO.model_validate(e) for e in service.list_active()]
