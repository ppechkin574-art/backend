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
"""

from uuid import UUID

from fastapi import APIRouter, Depends

from api.dependencies import allow_crm_access, get_crm_service
from auth.dtos.users import UserDTO
from crm.dtos import (
    CrmActivityDTO,
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
