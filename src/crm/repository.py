from sqlalchemy import func, select
from sqlalchemy.orm import Session

from crm.models import (
    CrmActivity,
    CrmTask,
    CrmTaskAssignee,
    CrmTaskAttachment,
    CrmTaskComment,
    CrmTaskLink,
)


class CrmRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---------- tasks ----------
    def list_tasks(self) -> list[CrmTask]:
        return list(
            self.db.scalars(
                select(CrmTask).order_by(CrmTask.sort_order, CrmTask.id)
            ).all()
        )

    def list_by_status(self, status: str) -> list[CrmTask]:
        return list(
            self.db.scalars(
                select(CrmTask)
                .where(CrmTask.status == status)
                .order_by(CrmTask.sort_order, CrmTask.id)
            ).all()
        )

    def get(self, task_id: int) -> CrmTask | None:
        return self.db.get(CrmTask, task_id)

    def add(self, task: CrmTask) -> CrmTask:
        self.db.add(task)
        self.db.flush()
        return task

    def delete(self, task: CrmTask) -> None:
        self.db.delete(task)
        self.db.flush()

    def max_sort_order(self, status: str) -> int:
        value = self.db.scalar(
            select(func.max(CrmTask.sort_order)).where(CrmTask.status == status)
        )
        return value if value is not None else -1

    # ---------- activity ----------
    def add_activity(self, activity: CrmActivity) -> CrmActivity:
        self.db.add(activity)
        self.db.flush()
        return activity

    def list_activity(self, limit: int = 200) -> list[CrmActivity]:
        return list(
            self.db.scalars(
                select(CrmActivity)
                .order_by(CrmActivity.created_at.desc(), CrmActivity.id.desc())
                .limit(limit)
            ).all()
        )

    # ---------- members (для дропдауна «ответственный») ----------
    def distinct_task_assignees(self) -> list[tuple]:
        rows = self.db.execute(
            select(CrmTask.assignee_admin_id, CrmTask.assignee_display)
            .where(CrmTask.assignee_admin_id.is_not(None))
            .distinct()
        ).all()
        return [(r[0], r[1]) for r in rows]

    def distinct_activity_admins(self) -> list[tuple]:
        rows = self.db.execute(
            select(CrmActivity.admin_id, CrmActivity.admin_display)
            .where(CrmActivity.admin_id.is_not(None))
            .distinct()
        ).all()
        return [(r[0], r[1]) for r in rows]

    # ---------- attachments ----------
    def list_attachments(self, task_id: int) -> list[CrmTaskAttachment]:
        return list(
            self.db.scalars(
                select(CrmTaskAttachment)
                .where(CrmTaskAttachment.task_id == task_id)
                .order_by(CrmTaskAttachment.created_at)
            ).all()
        )

    def get_attachment(self, attachment_id: int) -> CrmTaskAttachment | None:
        return self.db.get(CrmTaskAttachment, attachment_id)

    def add_attachment(self, attachment: CrmTaskAttachment) -> CrmTaskAttachment:
        self.db.add(attachment)
        self.db.flush()
        return attachment

    def delete_attachment(self, attachment: CrmTaskAttachment) -> None:
        self.db.delete(attachment)
        self.db.flush()

    # ---------- links ----------
    def list_link_ids(self, task_id: int) -> list[int]:
        return list(
            self.db.scalars(
                select(CrmTaskLink.linked_task_id)
                .where(CrmTaskLink.task_id == task_id)
                .order_by(CrmTaskLink.linked_task_id)
            ).all()
        )

    def list_link_ids_bulk(self, task_ids: list[int]) -> dict[int, list[int]]:
        out: dict[int, list[int]] = {tid: [] for tid in task_ids}
        if not task_ids:
            return out
        rows = self.db.execute(
            select(CrmTaskLink.task_id, CrmTaskLink.linked_task_id).where(
                CrmTaskLink.task_id.in_(task_ids)
            )
        ).all()
        for tid, linked_id in rows:
            out.setdefault(tid, []).append(linked_id)
        return out

    def get_link(self, task_id: int, linked_task_id: int) -> CrmTaskLink | None:
        return self.db.scalar(
            select(CrmTaskLink).where(
                CrmTaskLink.task_id == task_id,
                CrmTaskLink.linked_task_id == linked_task_id,
            )
        )

    def add_link(self, link: CrmTaskLink) -> CrmTaskLink:
        self.db.add(link)
        self.db.flush()
        return link

    def delete_link(self, link: CrmTaskLink) -> None:
        self.db.delete(link)
        self.db.flush()

    # ---------- assignees ----------
    def list_assignees(self, task_id: int) -> list[CrmTaskAssignee]:
        return list(
            self.db.scalars(
                select(CrmTaskAssignee)
                .where(CrmTaskAssignee.task_id == task_id)
                .order_by(CrmTaskAssignee.created_at)
            ).all()
        )

    def list_assignees_bulk(
        self, task_ids: list[int]
    ) -> dict[int, list[CrmTaskAssignee]]:
        out: dict[int, list[CrmTaskAssignee]] = {tid: [] for tid in task_ids}
        if not task_ids:
            return out
        rows = list(
            self.db.scalars(
                select(CrmTaskAssignee)
                .where(CrmTaskAssignee.task_id.in_(task_ids))
                .order_by(CrmTaskAssignee.created_at)
            ).all()
        )
        for row in rows:
            out.setdefault(row.task_id, []).append(row)
        return out

    def get_assignee(
        self, task_id: int, admin_id
    ) -> CrmTaskAssignee | None:
        return self.db.scalar(
            select(CrmTaskAssignee).where(
                CrmTaskAssignee.task_id == task_id,
                CrmTaskAssignee.admin_id == admin_id,
            )
        )

    def add_assignee(self, assignee: CrmTaskAssignee) -> CrmTaskAssignee:
        self.db.add(assignee)
        self.db.flush()
        return assignee

    def delete_assignee(self, assignee: CrmTaskAssignee) -> None:
        self.db.delete(assignee)
        self.db.flush()

    # ---------- comments ----------
    def list_comments(self, task_id: int) -> list[CrmTaskComment]:
        return list(
            self.db.scalars(
                select(CrmTaskComment)
                .where(CrmTaskComment.task_id == task_id)
                .order_by(CrmTaskComment.created_at)
            ).all()
        )

    def add_comment(self, comment: CrmTaskComment) -> CrmTaskComment:
        self.db.add(comment)
        self.db.flush()
        return comment
