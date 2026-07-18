"""Admin CRUD for events (banners + event cards on Главная screen).

Endpoints (all protected by allow_read_or_admin_write):
- GET    /admin/events           — list all (active + inactive)
- POST   /admin/events           — create
- GET    /admin/events/{id}      — get one
- PATCH  /admin/events/{id}      — partial update
- DELETE /admin/events/{id}      — hard delete
- POST   /admin/events/{id}/upload-icon — upload event icon to MinIO
"""

from fastapi import APIRouter, Depends, UploadFile, File

from api.dependencies import allow_read_or_admin_write, get_event_service, get_file_service
from events.dtos import EventCreateDTO, EventDTO, EventUpdateDTO
from events.service import EventService
from utils.file_service import FileService

router = APIRouter(
    prefix="/admin/events",
    tags=["admin"],
    dependencies=[Depends(allow_read_or_admin_write)],
)


def _enrich_icon(dto: EventDTO, file_service: FileService) -> EventDTO:
    if dto.icon_url and not dto.icon_url.startswith(("http://", "https://")):
        return dto.model_copy(update={"icon_url": file_service.get_event_icon_url(dto.icon_url)})
    return dto


@router.get("", response_model=list[EventDTO])
def list_events(
    service: EventService = Depends(get_event_service),
    file_service: FileService = Depends(get_file_service),
):
    return [_enrich_icon(EventDTO.model_validate(e), file_service) for e in service.list_all()]


@router.post("", response_model=EventDTO, status_code=201)
def create_event(
    body: EventCreateDTO,
    service: EventService = Depends(get_event_service),
    file_service: FileService = Depends(get_file_service),
):
    event = service.create(body)
    service.repo.db.commit()
    return _enrich_icon(EventDTO.model_validate(event), file_service)


@router.get("/{event_id}", response_model=EventDTO)
def get_event(
    event_id: int,
    service: EventService = Depends(get_event_service),
    file_service: FileService = Depends(get_file_service),
):
    return _enrich_icon(EventDTO.model_validate(service.get_one(event_id)), file_service)


@router.patch("/{event_id}", response_model=EventDTO)
def update_event(
    event_id: int,
    body: EventUpdateDTO,
    service: EventService = Depends(get_event_service),
    file_service: FileService = Depends(get_file_service),
):
    event = service.update(event_id, body)
    service.repo.db.commit()
    return _enrich_icon(EventDTO.model_validate(event), file_service)


@router.delete("/{event_id}", status_code=204)
def delete_event(
    event_id: int,
    service: EventService = Depends(get_event_service),
):
    service.delete(event_id)
    service.repo.db.commit()


@router.post("/{event_id}/upload-icon", response_model=EventDTO)
async def upload_event_icon(
    event_id: int,
    file: UploadFile = File(...),
    service: EventService = Depends(get_event_service),
    file_service: FileService = Depends(get_file_service),
):
    """Загружает иконку события в MinIO и сохраняет object key в event.icon_url."""
    event = service.get_one(event_id)
    object_key = await file_service.save_event_icon(file)
    event.icon_url = object_key
    service.repo.db.commit()
    return _enrich_icon(EventDTO.model_validate(event), file_service)
