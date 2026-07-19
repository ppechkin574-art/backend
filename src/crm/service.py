import io
import logging
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from fastapi import HTTPException, status

from clients.media_storage.exceptions import MediaStorageError
from crm.attachments import (
    MAX_ATTACHMENT_SIZE_BYTES,
    is_blocked_extension,
    sanitize_filename,
    sniff_dangerous,
)
from crm.dtos import CrmMoveDTO, CrmTaskCreateDTO, CrmTaskUpdateDTO
from crm.models import (
    CrmActivity,
    CrmTask,
    CrmTaskAssignee,
    CrmTaskAttachment,
    CrmTaskComment,
    CrmTaskLink,
)
from crm.repository import CrmRepository

if TYPE_CHECKING:
    from clients.agent_webhook.client import AgentWebhookClient
    from clients.media_storage.client import MediaStorageClientInterface

logger = logging.getLogger(__name__)


class CrmService:
    ATTACHMENT_PREFIX = "crm-attachments"
    MAX_ATTACHMENT_SIZE_BYTES = MAX_ATTACHMENT_SIZE_BYTES

    def __init__(
        self,
        repo: CrmRepository,
        agent_webhook: "AgentWebhookClient | None" = None,
        agent_admin_id: str | None = None,
        media_storage: "MediaStorageClientInterface | None" = None,
    ):
        self.repo = repo
        self._agent_webhook = agent_webhook
        # Compared as strings — env value has no UUID validation upstream.
        self._agent_admin_id = agent_admin_id or None
        # Webhooks are QUEUED during the operation and sent only after the
        # router commits (flush_webhooks) — firing pre-commit made the
        # executor re-read the board and see the OLD state (live-caught race).
        self._pending_webhooks: list[tuple[str, dict]] = []
        # Injected directly (not via FileService) — FileService's pipeline
        # is PIL-based and image-specific (resize/re-encode/magic-byte
        # sniff for image formats only). CRM attachments are arbitrary
        # files (pdf/docx/xlsx/zip/...), so we talk to the storage
        # interface directly and keep the image pipeline untouched.
        self._media_storage = media_storage

    # ---------- reads ----------
    def list_tasks(self) -> list[CrmTask]:
        tasks = self.repo.list_tasks()
        self._attach_relations_bulk(tasks)
        return tasks

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

    # ---------- relation enrichment (linked tasks / extra assignees) ----------
    def _attach_relations(self, task: CrmTask) -> None:
        """Sets transient (non-persisted) attributes on the ORM instance so
        CrmTaskDTO.model_validate(task, from_attributes=True) can read
        them — these are NOT mapped columns, just plain attributes."""
        task.linked_task_ids = self.repo.list_link_ids(task.id)
        task.extra_assignees = [
            {"id": a.admin_id, "display": a.admin_display}
            for a in self.repo.list_assignees(task.id)
        ]

    def _attach_relations_bulk(self, tasks: list[CrmTask]) -> None:
        ids = [t.id for t in tasks]
        links_map = self.repo.list_link_ids_bulk(ids)
        assignees_map = self.repo.list_assignees_bulk(ids)
        for t in tasks:
            t.linked_task_ids = links_map.get(t.id, [])
            t.extra_assignees = [
                {"id": a.admin_id, "display": a.admin_display}
                for a in assignees_map.get(t.id, [])
            ]

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

    def _maybe_dispatch_agent_webhook(self, task: CrmTask) -> None:
        """Queues the assigned-webhook if this task's assignee is the
        agent — called both on creation-with-assignee and on a later
        reassignment, since either can be how a task ends up on the agent."""
        if (
            self._agent_webhook is not None
            and self._agent_admin_id
            and task.assignee_admin_id is not None
            and str(task.assignee_admin_id) == self._agent_admin_id
        ):
            self._pending_webhooks.append(
                ("assigned", self._agent_webhook.task_payload(task))
            )

    def _dispatch_board_event(
        self, event_type: str, task: CrmTask | None, change: dict | None = None
    ) -> None:
        if self._agent_webhook is not None:
            self._pending_webhooks.append(
                (
                    "event",
                    {
                        "type": event_type,
                        "task": self._agent_webhook.task_payload(task)
                        if task is not None
                        else None,
                        "change": change or {},
                    },
                )
            )

    def flush_webhooks(self) -> None:
        """Call AFTER commit — sends the queued webhooks so the executor's
        follow-up board read is guaranteed to see the committed state."""
        pending, self._pending_webhooks = self._pending_webhooks, []
        if self._agent_webhook is None:
            return
        for kind, payload in pending:
            if kind == "assigned":
                self._agent_webhook.send_task_assigned(payload)
            else:
                self._agent_webhook.send_board_event(payload)

    def _enforce_wip_limit(self, task_id: int | None, new_status: str) -> None:
        """Hard WIP limit: at most ONE task in «В работе» (prog), for
        everyone — humans and agent alike (explicit product decision)."""
        if new_status != "prog":
            return
        occupied = [
            t for t in self.repo.list_by_status("prog") if t.id != task_id
        ]
        if occupied:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"В колонке «В работе» уже есть задача "
                    f"«{occupied[0].title}» (№{occupied[0].id}) — "
                    f"одновременно в работе может быть только одна задача"
                ),
            )

    def create(
        self, payload: CrmTaskCreateDTO, actor_id: UUID | None, actor_display: str
    ) -> CrmTask:
        self._enforce_wip_limit(None, payload.status)
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
        self._dispatch_board_event("create", task)
        self._maybe_dispatch_agent_webhook(task)
        self._attach_relations(task)
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
        if "status" in fields:
            self._enforce_wip_limit(task_id, fields["status"])
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
            self._dispatch_board_event(
                "move", task, {"from": old_status, "to": task.status}
            )
        else:
            self._log(
                task,
                "edit",
                {"fields": list(fields.keys())},
                actor_id,
                actor_display,
            )
            self._dispatch_board_event("edit", task, {"fields": list(fields.keys())})

        if "assignee_admin_id" in fields and str(task.assignee_admin_id) != str(old_assignee):
            self._maybe_dispatch_agent_webhook(task)

        self._attach_relations(task)
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
        self._enforce_wip_limit(task_id, new_status)

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
            self._dispatch_board_event(
                "move", task, {"from": old_status, "to": new_status}
            )
        self._attach_relations(task)
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
        self._dispatch_board_event("delete", task)
        self.repo.delete(task)

    # ---------- attachments ----------
    def list_attachments(self, task_id: int) -> list[CrmTaskAttachment]:
        self.get_one(task_id)
        return self.repo.list_attachments(task_id)

    def add_attachment(
        self,
        task_id: int,
        filename: str,
        content_type: str | None,
        content: bytes,
        actor_id: UUID | None,
        actor_display: str,
    ) -> CrmTaskAttachment:
        task = self.get_one(task_id)

        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Пустой файл"
            )
        if len(content) > self.MAX_ATTACHMENT_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Файл слишком большой. Максимум "
                    f"{self.MAX_ATTACHMENT_SIZE_BYTES // (1024 * 1024)}MB"
                ),
            )
        if is_blocked_extension(filename):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Этот тип файла запрещён к загрузке",
            )
        if sniff_dangerous(content[:64]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Файл похож на исполняемый — загрузка запрещена",
            )
        if self._media_storage is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Хранилище файлов не настроено",
            )

        safe_name = sanitize_filename(filename)
        object_name = f"{self.ATTACHMENT_PREFIX}/{task_id}/{uuid4().hex}_{safe_name}"

        try:
            self._media_storage.save(object_name, io.BytesIO(content))
        except MediaStorageError as e:
            logger.exception("Failed to save CRM attachment %s", object_name)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Не удалось сохранить файл",
            ) from e

        attachment = CrmTaskAttachment(
            task_id=task_id,
            object_name=object_name,
            filename=safe_name,
            content_type=content_type,
            size=len(content),
            uploaded_by=actor_id,
            uploaded_by_display=actor_display,
        )
        self.repo.add_attachment(attachment)
        self._log(
            task,
            "attach",
            {"filename": safe_name, "attachment_id": attachment.id},
            actor_id,
            actor_display,
        )
        return attachment

    def remove_attachment(
        self,
        task_id: int,
        attachment_id: int,
        actor_id: UUID | None,
        actor_display: str,
    ) -> None:
        task = self.get_one(task_id)
        attachment = self.repo.get_attachment(attachment_id)
        if attachment is None or attachment.task_id != task_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Вложение с id={attachment_id} не найдено",
            )
        object_name = attachment.object_name
        filename = attachment.filename
        self.repo.delete_attachment(attachment)

        if self._media_storage is not None:
            try:
                self._media_storage.remove(object_name)
            except MediaStorageError:
                logger.warning(
                    "Failed to remove CRM attachment object %s from storage",
                    object_name,
                )

        self._log(
            task,
            "unattach",
            {"filename": filename, "attachment_id": attachment_id},
            actor_id,
            actor_display,
        )

    def attachment_url(self, attachment: CrmTaskAttachment) -> str:
        if self._media_storage is None:
            return ""
        try:
            return self._media_storage.link(attachment.object_name)
        except MediaStorageError:
            logger.warning(
                "Failed to build URL for CRM attachment %s", attachment.object_name
            )
            return ""

    # ---------- links ("связано с") ----------
    def list_links(self, task_id: int) -> list[int]:
        self.get_one(task_id)
        return self.repo.list_link_ids(task_id)

    def add_link(
        self,
        task_id: int,
        linked_task_id: int,
        actor_id: UUID | None,
        actor_display: str,
    ) -> CrmTask:
        if task_id == linked_task_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Нельзя связать задачу саму с собой",
            )
        task = self.get_one(task_id)
        self.get_one(linked_task_id)

        if self.repo.get_link(task_id, linked_task_id) is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Эти задачи уже связаны",
            )

        self.repo.add_link(CrmTaskLink(task_id=task_id, linked_task_id=linked_task_id))
        self.repo.add_link(CrmTaskLink(task_id=linked_task_id, linked_task_id=task_id))
        self._log(
            task,
            "link",
            {"linked_task_id": linked_task_id},
            actor_id,
            actor_display,
        )
        self._attach_relations(task)
        return task

    def remove_link(
        self,
        task_id: int,
        linked_task_id: int,
        actor_id: UUID | None,
        actor_display: str,
    ) -> CrmTask:
        task = self.get_one(task_id)
        link = self.repo.get_link(task_id, linked_task_id)
        if link is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Связь между этими задачами не найдена",
            )
        reverse = self.repo.get_link(linked_task_id, task_id)
        self.repo.delete_link(link)
        if reverse is not None:
            self.repo.delete_link(reverse)

        self._log(
            task,
            "unlink",
            {"linked_task_id": linked_task_id},
            actor_id,
            actor_display,
        )
        self._attach_relations(task)
        return task

    # ---------- extra assignees ----------
    def list_assignees(self, task_id: int) -> list[CrmTaskAssignee]:
        self.get_one(task_id)
        return self.repo.list_assignees(task_id)

    def add_assignee(
        self,
        task_id: int,
        admin_id: UUID,
        admin_display: str,
        actor_id: UUID | None,
        actor_display: str,
    ) -> CrmTask:
        task = self.get_one(task_id)
        if self.repo.get_assignee(task_id, admin_id) is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Этот админ уже в списке ответственных",
            )
        self.repo.add_assignee(
            CrmTaskAssignee(
                task_id=task_id, admin_id=admin_id, admin_display=admin_display
            )
        )
        self._log(
            task,
            "assign_extra",
            {"admin_id": str(admin_id), "admin_display": admin_display},
            actor_id,
            actor_display,
        )
        self._attach_relations(task)
        return task

    def remove_assignee(
        self,
        task_id: int,
        admin_id: UUID,
        actor_id: UUID | None,
        actor_display: str,
    ) -> CrmTask:
        task = self.get_one(task_id)
        assignee = self.repo.get_assignee(task_id, admin_id)
        if assignee is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ответственный не найден среди дополнительных для этой задачи",
            )
        self.repo.delete_assignee(assignee)
        self._log(
            task,
            "unassign_extra",
            {"admin_id": str(admin_id)},
            actor_id,
            actor_display,
        )
        self._attach_relations(task)
        return task

    # ---------- comments ----------
    def list_comments(self, task_id: int) -> list[CrmTaskComment]:
        self.get_one(task_id)
        return self.repo.list_comments(task_id)

    def add_comment(
        self,
        task_id: int,
        text: str,
        actor_id: UUID | None,
        actor_display: str,
    ) -> CrmTaskComment:
        task = self.get_one(task_id)
        comment = CrmTaskComment(
            task_id=task_id,
            admin_id=actor_id,
            admin_display=actor_display,
            text=text,
        )
        self.repo.add_comment(comment)
        self._log(
            task,
            "comment",
            {"comment_id": comment.id},
            actor_id,
            actor_display,
        )
        return comment
