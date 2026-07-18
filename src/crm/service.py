from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException, status

from crm.dtos import CrmMoveDTO, CrmTaskCreateDTO, CrmTaskUpdateDTO
from crm.models import CrmActivity, CrmTask
from crm.repository import CrmRepository

if TYPE_CHECKING:
    from clients.agent_webhook.client import AgentWebhookClient


class CrmService:
    def __init__(
        self,
        repo: CrmRepository,
        agent_webhook: "AgentWebhookClient | None" = None,
        agent_admin_id: str | None = None,
    ):
        self.repo = repo
        self._agent_webhook = agent_webhook
        # Compared as strings — env value has no UUID validation upstream.
        self._agent_admin_id = agent_admin_id or None

    # ---------- reads ----------
    def list_tasks(self) -> list[CrmTask]:
        return self.repo.list_tasks()

    def list_activity(self, limit: int = 200) -> list[CrmActivity]:
        return self.repo.list_activity(limit)

    def get_one(self, task_id: int) -> CrmTask:
        task = self.repo.get(task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Задача с id={task_id} не найдена",
            )
        return task

    def list_members(
        self, current_id: UUID | None, current_display: str
    ) -> list[dict]:
        """Кандидаты в ответственные: текущий админ + все, кто уже фигурирует
        на доске (как ответственный или как автор действия в логе)."""
        seen: dict[str, dict] = {}
        if current_id is not None:
            seen[str(current_id)] = {"id": current_id, "display": current_display}
        for admin_id, display in self.repo.distinct_task_assignees():
            key = str(admin_id)
            if admin_id is not None and key not in seen:
                seen[key] = {"id": admin_id, "display": display or key}
        for admin_id, display in self.repo.distinct_activity_admins():
            key = str(admin_id)
            if admin_id is not None and key not in seen:
                seen[key] = {"id": admin_id, "display": display or key}
        return list(seen.values())

    # ---------- writes ----------
    def _log(
        self,
        task: CrmTask | None,
        action: str,
        details: dict,
        actor_id: UUID | None,
        actor_display: str,
        task_title: str | None = None,
    ) -> None:
        self.repo.add_activity(
            CrmActivity(
                task_id=task.id if task is not None else None,
                task_title=task.title if task is not None else (task_title or ""),
                admin_id=actor_id,
                admin_display=actor_display,
                action=action,
                details=details,
            )
        )

    def create(
        self, payload: CrmTaskCreateDTO, actor_id: UUID | None, actor_display: str
    ) -> CrmTask:
        task = CrmTask(
            title=payload.title,
            description=payload.description or "",
            status=payload.status,
            priority=payload.priority,
            assignee_admin_id=payload.assignee_admin_id,
            assignee_display=payload.assignee_display,
            due_date=payload.due_date,
            labels=payload.labels or [],
            sort_order=self.repo.max_sort_order(payload.status) + 1,
            created_by=actor_id,
        )
        self.repo.add(task)
        self._log(task, "create", {"status": task.status}, actor_id, actor_display)
        return task

    def update(
        self,
        task_id: int,
        payload: CrmTaskUpdateDTO,
        actor_id: UUID | None,
        actor_display: str,
    ) -> CrmTask:
        task = self.get_one(task_id)
        fields = payload.model_dump(exclude_unset=True)
        old_status = task.status
        old_assignee = task.assignee_admin_id
        for field, value in fields.items():
            setattr(task, field, value)
        self.repo.db.flush()

        if "status" in fields and fields["status"] != old_status:
            self._log(
                task,
                "move",
                {"from": old_status, "to": task.status},
                actor_id,
                actor_display,
            )
        else:
            self._log(
                task,
                "edit",
                {"fields": list(fields.keys())},
                actor_id,
                actor_display,
            )

        if (
            "assignee_admin_id" in fields
            and str(task.assignee_admin_id) != str(old_assignee)
            and self._agent_webhook is not None
            and self._agent_admin_id
            and str(task.assignee_admin_id) == self._agent_admin_id
        ):
            self._agent_webhook.notify_task_assigned(task)

        return task

    def move(
        self,
        task_id: int,
        payload: CrmMoveDTO,
        actor_id: UUID | None,
        actor_display: str,
    ) -> CrmTask:
        task = self.get_one(task_id)
        old_status = task.status
        new_status = payload.status

        # target column without this task, in current order
        column = [t for t in self.repo.list_by_status(new_status) if t.id != task.id]
        position = max(0, min(payload.position, len(column)))
        column.insert(position, task)
        task.status = new_status
        for index, item in enumerate(column):
            item.sort_order = index

        # renumber the source column too, if the card left it
        if old_status != new_status:
            source = [
                t for t in self.repo.list_by_status(old_status) if t.id != task.id
            ]
            for index, item in enumerate(source):
                item.sort_order = index

        self.repo.db.flush()

        # log only real status changes; pure in-column reorders are not noise-logged
        if old_status != new_status:
            self._log(
                task,
                "move",
                {"from": old_status, "to": new_status},
                actor_id,
                actor_display,
            )
        return task

    def delete(
        self, task_id: int, actor_id: UUID | None, actor_display: str
    ) -> None:
        task = self.get_one(task_id)
        title = task.title
        # записываем лог ДО удаления, task_id обнуляем — задача исчезнет,
        # а история останется
        self._log(
            None,
            "delete",
            {},
            actor_id,
            actor_display,
            task_title=title,
        )
        self.repo.delete(task)
