from sqlalchemy import Column, Date, DateTime, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from database import Base


class CrmTask(Base):
    """Задача на доске CRM (внутренний таск-трекер команды)."""

    __tablename__ = "crm_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False, server_default="")
    # статусы = колонки доски: todo | prog | hold | done
    status = Column(String(20), nullable=False, server_default="todo")
    # приоритет: low | mid | high
    priority = Column(String(20), nullable=False, server_default="mid")
    # ответственный: Keycloak user id (sub) + денормализованное имя для отображения
    assignee_admin_id = Column(UUID(as_uuid=True), nullable=True)
    assignee_display = Column(String(200), nullable=True)
    due_date = Column(Date, nullable=True)
    labels = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))  # list[str]
    # порядок внутри колонки (для drag-n-drop)
    sort_order = Column(Integer, nullable=False, server_default="0")
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CrmActivity(Base):
    """Append-only лента изменений доски (кто что сделал и когда).

    task_id может стать NULL после удаления задачи — запись остаётся в истории.
    task_title денормализован, чтобы лог читался даже без самой задачи.
    """

    __tablename__ = "crm_activity_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, nullable=True)
    task_title = Column(String(200), nullable=False)
    admin_id = Column(UUID(as_uuid=True), nullable=True)
    admin_display = Column(String(200), nullable=False)
    # create | move | edit | delete
    action = Column(String(50), nullable=False)
    details = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
