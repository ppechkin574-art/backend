from sqlalchemy import func, select
from sqlalchemy.orm import Session

from crm.models import CrmActivity, CrmTask


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
