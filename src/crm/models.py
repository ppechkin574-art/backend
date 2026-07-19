from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
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


class CrmTaskAttachment(Base):
    """Файл, приложенный к карточке задачи. Само содержимое лежит в S3
    (MinIO) под ``object_name`` — здесь только метаданные."""

    __tablename__ = "crm_task_attachments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(
        Integer,
        ForeignKey("crm_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    object_name = Column(String(600), nullable=False)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=True)
    size = Column(Integer, nullable=False)
    uploaded_by = Column(UUID(as_uuid=True), nullable=True)
    uploaded_by_display = Column(String(200), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CrmTaskLink(Base):
    """«Связано с» между двумя карточками. Симметричная связь хранится
    как одна строка НА КАЖДОЕ направление (task_id -> linked_task_id и
    обратно) — так чтение списка связей одной задачи остаётся простым
    select-ом без UNION/OR."""

    __tablename__ = "crm_task_links"
    __table_args__ = (
        UniqueConstraint("task_id", "linked_task_id", name="uq_crm_task_links_pair"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(
        Integer,
        ForeignKey("crm_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    linked_task_id = Column(
        Integer, ForeignKey("crm_tasks.id", ondelete="CASCADE"), nullable=False
    )
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CrmTaskAssignee(Base):
    """Дополнительный ответственный по задаче — НЕ заменяет основной
    ``CrmTask.assignee_admin_id``/``assignee_display`` (те продолжает
    читать внешний агентский фреймворк как primary assignee)."""

    __tablename__ = "crm_task_assignees"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "admin_id", name="uq_crm_task_assignees_pair"
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(
        Integer,
        ForeignKey("crm_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    admin_id = Column(UUID(as_uuid=True), nullable=False)
    admin_display = Column(String(200), nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CrmTaskComment(Base):
    """Отдельная лента комментариев к карточке — НЕ пересекается с
    механизмом ``update_crm_task(comment=...)`` у агента (тот дописывает
    в description)."""

    __tablename__ = "crm_task_comments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(
        Integer,
        ForeignKey("crm_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    admin_id = Column(UUID(as_uuid=True), nullable=True)
    admin_display = Column(String(200), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
