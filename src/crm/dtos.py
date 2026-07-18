import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

_STATUSES = ("todo", "prog", "hold", "done")
_PRIORITIES = ("low", "mid", "high")


class CrmTaskDTO(BaseModel):
    id: int
    title: str
    description: str
    status: str
    priority: str
    assignee_admin_id: UUID | None = None
    assignee_display: str | None = None
    due_date: datetime.date | None = None
    labels: list[str] = Field(default_factory=list)
    sort_order: int
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


class CrmTaskCreateDTO(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    status: str = "todo"
    priority: str = "mid"
    assignee_admin_id: UUID | None = None
    assignee_display: str | None = Field(default=None, max_length=200)
    due_date: datetime.date | None = None
    labels: list[str] = Field(default_factory=list)

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        if v not in _STATUSES:
            raise ValueError(f"status must be one of {list(_STATUSES)}")
        return v

    @field_validator("priority")
    @classmethod
    def _validate_priority(cls, v: str) -> str:
        if v not in _PRIORITIES:
            raise ValueError(f"priority must be one of {list(_PRIORITIES)}")
        return v

    @field_validator("labels")
    @classmethod
    def _normalize_labels(cls, v: list[str]) -> list[str]:
        return [str(x)[:40] for x in v][:20]


class CrmTaskUpdateDTO(BaseModel):
    """Все поля опциональны — PATCH обновляет только переданные."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    status: str | None = None
    priority: str | None = None
    assignee_admin_id: UUID | None = None
    assignee_display: str | None = Field(default=None, max_length=200)
    due_date: datetime.date | None = None
    labels: list[str] | None = None

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in _STATUSES:
            raise ValueError(f"status must be one of {list(_STATUSES)}")
        return v

    @field_validator("priority")
    @classmethod
    def _validate_priority(cls, v: str | None) -> str | None:
        if v is not None and v not in _PRIORITIES:
            raise ValueError(f"priority must be one of {list(_PRIORITIES)}")
        return v

    @field_validator("labels")
    @classmethod
    def _normalize_labels(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        return [str(x)[:40] for x in v][:20]


class CrmMoveDTO(BaseModel):
    """Перемещение карточки при drag-n-drop: целевая колонка + позиция в ней."""

    status: str
    position: int = Field(default=0, ge=0)

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        if v not in _STATUSES:
            raise ValueError(f"status must be one of {list(_STATUSES)}")
        return v


class CrmActivityDTO(BaseModel):
    id: int
    task_id: int | None = None
    task_title: str
    admin_id: UUID | None = None
    admin_display: str
    action: str
    details: dict = Field(default_factory=dict)
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class CrmMemberDTO(BaseModel):
    """Админ, которого можно назначить ответственным."""

    id: UUID
    display: str
