"""Public read-only endpoint for events (banners + cards on Главная screen).

App fetches this on HomeMainScreen mount — no auth required.
"""

from fastapi import APIRouter, Depends

from api.dependencies import get_event_service, get_file_service
from events.dtos import EventDTO
from events.service import EventService
from utils.file_service import FileService

router = APIRouter(prefix="/events", tags=["user"])


def _enrich_icon(dto: EventDTO, file_service: FileService) -> EventDTO:
    if dto.icon_url and not dto.icon_url.startswith(("http://", "https://")):
        return dto.model_copy(update={"icon_url": file_service.get_event_icon_url(dto.icon_url)})
    return dto


@router.get("", response_model=list[EventDTO])
def list_active_events(
    service: EventService = Depends(get_event_service),
    file_service: FileService = Depends(get_file_service),
):
    return [_enrich_icon(EventDTO.model_validate(e), file_service) for e in service.list_active()]
