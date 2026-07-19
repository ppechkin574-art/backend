"""Admin CRM board — внутренний таск-трекер команды (канбан) + лог изменений.

Endpoints (protected by allow_crm_access — admin/manager full access;
marketing gets the same access EXCEPT deleting a task):
- GET    /admin/crm/tasks             — список задач
- POST   /admin/crm/tasks             — создать
- PATCH  /admin/crm/tasks/{id}        — частичное обновление (детали)
- PATCH  /admin/crm/tasks/{id}/move   — сменить статус/позицию (drag-n-drop)
- DELETE /admin/crm/tasks/{id}        — удалить (admin/manager only)
- GET    /admin/crm/activity          — лента изменений (кто что сделал)
- GET    /admin/crm/members           — админы для дропдауна «ответственный»

- POST   /admin/crm/tasks/{id}/attachments               — прикрепить файл
- GET    /admin/crm/tasks/{id}/attachments               — список вложений
- DELETE /admin/crm/tasks/{id}/attachments/{aid}         — удалить вложение
- POST   /admin/crm/tasks/{id}/links                     — связать с другой задачей
- DELETE /admin/crm/tasks/{id}/links/{linked_id}         — убрать связь
- POST   /admin/crm/tasks/{id}/assignees                 — добавить доп. ответственного
- DELETE /admin/crm/tasks/{id}/assignees/{admin_id}      — убрать доп. ответственного
- POST   /admin/crm/tasks/{id}/comments                  — добавить комментарий
- GET    /admin/crm/tasks/{id}/comments                  — лента комментариев
"""

from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile

from api.dependencies import allow_crm_access, get_crm_service
from auth.dtos.users import UserDTO
from crm.dtos import (
    CrmActivityDTO,
    CrmAssigneeCreateDTO,
    CrmAttachmentDTO,
    CrmCommentCreateDTO,
    CrmCommentDTO,
    CrmLinkCreateDTO,
    CrmMemberDTO,
    CrmMoveDTO,
    CrmTaskCreateDTO,
    CrmTaskDTO,
    CrmTaskUpdateDTO,
)
from crm.service import CrmService

router = APIRouter(
    prefix="/admin/crm",
    tags=["admin"],
    dependencies=[Depends(allow_crm_access)],
)


def _actor(user: UserDTO) -> tuple[UUID, str]:
    """Идентификатор и отображаемое имя админа для лога изменений."""
    return user.id, (user.name or user.email or str(user.id))


@router.get("/tasks", response_model=list[CrmTaskDTO])
def list_tasks(service: CrmService = Depends(get_crm_service)):
    return [CrmTaskDTO.model_validate(t) for t in service.list_tasks()]


@router.post("/tasks", response_model=CrmTaskDTO, status_code=201)
def create_task(
    body: CrmTaskCreateDTO,
    user: UserDTO = Depends(allow_crm_access),
    service: CrmService = Depends(get_crm_service),
):
    actor_id, actor_display = _actor(user)
    task = service.create(body, actor_id, actor_display)
    service.repo.db.commit()
    service.flush_webhooks()
    return CrmTaskDTO.model_validate(task)


@router.patch("/tasks/{task_id}", response_model=CrmTaskDTO)
def update_task(
    task_id: int,
    body: CrmTaskUpdateDTO,
    user: UserDTO = Depends(allow_crm_access),
    service: CrmService = Depends(get_crm_service),
):
    actor_id, actor_display = _actor(user)
    task = service.update(task_id, body, actor_id, actor_display)
    service.repo.db.commit()
    service.flush_webhooks()
    return CrmTaskDTO.model_validate(task)


@router.patch("/tasks/{task_id}/move", response_model=CrmTaskDTO)
def move_task(
    task_id: int,
    body: CrmMoveDTO,
    user: UserDTO = Depends(allow_crm_access),
    service: CrmService = Depends(get_crm_service),
):
    actor_id, actor_display = _actor(user)
    task = service.move(task_id, body, actor_id, actor_display)
    service.repo.db.commit()
    service.flush_webhooks()
    return CrmTaskDTO.model_validate(task)


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(
    task_id: int,
    user: UserDTO = Depends(allow_crm_access),
    service: CrmService = Depends(get_crm_service),
):
    actor_id, actor_display = _actor(user)
    service.delete(task_id, actor_id, actor_display)
    service.repo.db.commit()
    service.flush_webhooks()


@router.get("/activity", response_model=list[CrmActivityDTO])
def list_activity(service: CrmService = Depends(get_crm_service)):
    return [CrmActivityDTO.model_validate(a) for a in service.list_activity()]


@router.get("/members", response_model=list[CrmMemberDTO])
def list_members(
    user: UserDTO = Depends(allow_crm_access),
    service: CrmService = Depends(get_crm_service),
):
    actor_id, actor_display = _actor(user)
    return [CrmMemberDTO(**m) for m in service.list_members(actor_id, actor_display)]


# ---------- attachments ----------


@router.post(
    "/tasks/{task_id}/attachments", response_model=CrmAttachmentDTO, status_code=201
)
async def upload_attachment(
    task_id: int,
    file: UploadFile = File(...),
    user: UserDTO = Depends(allow_crm_access),
    service: CrmService = Depends(get_crm_service),
):
    actor_id, actor_display = _actor(user)
    content = await file.read()
    attachment = service.add_attachment(
        task_id,
        file.filename or "file",
        file.content_type,
        content,
        actor_id,
        actor_display,
    )
    service.repo.db.commit()
    service.flush_webhooks()
    dto = CrmAttachmentDTO.model_validate(attachment)
    dto.url = service.attachment_url(attachment)
    return dto


@router.get("/tasks/{task_id}/attachments", response_model=list[CrmAttachmentDTO])
def list_attachments(
    task_id: int,
    service: CrmService = Depends(get_crm_service),
):
    result = []
    for attachment in service.list_attachments(task_id):
        dto = CrmAttachmentDTO.model_validate(attachment)
        dto.url = service.attachment_url(attachment)
        result.append(dto)
    return result


@router.delete("/tasks/{task_id}/attachments/{attachment_id}", status_code=204)
def delete_attachment(
    task_id: int,
    attachment_id: int,
    user: UserDTO = Depends(allow_crm_access),
    service: CrmService = Depends(get_crm_service),
):
    actor_id, actor_display = _actor(user)
    service.remove_attachment(task_id, attachment_id, actor_id, actor_display)
    service.repo.db.commit()
    service.flush_webhooks()


# ---------- links ("связано с") ----------


@router.post("/tasks/{task_id}/links", response_model=CrmTaskDTO)
def add_link(
    task_id: int,
    body: CrmLinkCreateDTO,
    user: UserDTO = Depends(allow_crm_access),
    service: CrmService = Depends(get_crm_service),
):
    actor_id, actor_display = _actor(user)
    task = service.add_link(task_id, body.linked_task_id, actor_id, actor_display)
    service.repo.db.commit()
    service.flush_webhooks()
    return CrmTaskDTO.model_validate(task)


@router.delete("/tasks/{task_id}/links/{linked_task_id}", response_model=CrmTaskDTO)
def remove_link(
    task_id: int,
    linked_task_id: int,
    user: UserDTO = Depends(allow_crm_access),
    service: CrmService = Depends(get_crm_service),
):
    actor_id, actor_display = _actor(user)
    task = service.remove_link(task_id, linked_task_id, actor_id, actor_display)
    service.repo.db.commit()
    service.flush_webhooks()
    return CrmTaskDTO.model_validate(task)


# ---------- extra assignees ----------


@router.post("/tasks/{task_id}/assignees", response_model=CrmTaskDTO)
def add_assignee(
    task_id: int,
    body: CrmAssigneeCreateDTO,
    user: UserDTO = Depends(allow_crm_access),
    service: CrmService = Depends(get_crm_service),
):
    actor_id, actor_display = _actor(user)
    task = service.add_assignee(
        task_id, body.admin_id, body.admin_display, actor_id, actor_display
    )
    service.repo.db.commit()
    service.flush_webhooks()
    return CrmTaskDTO.model_validate(task)


@router.delete("/tasks/{task_id}/assignees/{admin_id}", response_model=CrmTaskDTO)
def remove_assignee(
    task_id: int,
    admin_id: UUID,
    user: UserDTO = Depends(allow_crm_access),
    service: CrmService = Depends(get_crm_service),
):
    actor_id, actor_display = _actor(user)
    task = service.remove_assignee(task_id, admin_id, actor_id, actor_display)
    service.repo.db.commit()
    service.flush_webhooks()
    return CrmTaskDTO.model_validate(task)


# ---------- comments ----------


@router.post(
    "/tasks/{task_id}/comments", response_model=CrmCommentDTO, status_code=201
)
def add_comment(
    task_id: int,
    body: CrmCommentCreateDTO,
    user: UserDTO = Depends(allow_crm_access),
    service: CrmService = Depends(get_crm_service),
):
    actor_id, actor_display = _actor(user)
    comment = service.add_comment(task_id, body.text, actor_id, actor_display)
    service.repo.db.commit()
    return CrmCommentDTO.model_validate(comment)


@router.get("/tasks/{task_id}/comments", response_model=list[CrmCommentDTO])
def list_comments(
    task_id: int,
    service: CrmService = Depends(get_crm_service),
):
    return [CrmCommentDTO.model_validate(c) for c in service.list_comments(task_id)]
