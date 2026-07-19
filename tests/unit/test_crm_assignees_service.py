"""Unit tests for CrmService's extra-assignee methods.

Critically pins that adding/removing an EXTRA assignee never touches
the primary ``CrmTask.assignee_admin_id``/``assignee_display`` columns
— those are read by the external agent framework as the primary
assignee and must stay untouched by this feature.
"""

import datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from crm.models import CrmTask, CrmTaskAssignee
from crm.service import CrmService


def _make_service(repo=None):
    if repo is None:
        repo = MagicMock()
    return CrmService(repo), repo


def _task(task_id: int = 1) -> CrmTask:
    primary_admin = uuid4()
    return CrmTask(
        id=task_id,
        title="Task",
        status="todo",
        priority="mid",
        assignee_admin_id=primary_admin,
        assignee_display="Primary Admin",
    )


class TestAddAssignee:
    def test_success(self):
        service, repo = _make_service()
        task = _task(1)
        original_primary_id = task.assignee_admin_id
        original_primary_display = task.assignee_display
        repo.get.return_value = task
        repo.get_assignee.return_value = None
        repo.list_link_ids.return_value = []
        repo.list_assignees.return_value = []

        admin_id = uuid4()
        result = service.add_assignee(1, admin_id, "Extra Admin", None, "Actor")

        repo.add_assignee.assert_called_once()
        added = repo.add_assignee.call_args.args[0]
        assert added.task_id == 1
        assert added.admin_id == admin_id
        assert added.admin_display == "Extra Admin"

        # Primary assignee fields must remain untouched.
        assert result.assignee_admin_id == original_primary_id
        assert result.assignee_display == original_primary_display

        repo.add_activity.assert_called_once()
        assert repo.add_activity.call_args.args[0].action == "assign_extra"

    def test_duplicate_rejected(self):
        service, repo = _make_service()
        repo.get.return_value = _task(1)
        admin_id = uuid4()
        repo.get_assignee.return_value = CrmTaskAssignee(
            id=1, task_id=1, admin_id=admin_id, admin_display="Extra"
        )
        with pytest.raises(HTTPException) as exc:
            service.add_assignee(1, admin_id, "Extra", None, "Actor")
        assert exc.value.status_code == 400
        repo.add_assignee.assert_not_called()

    def test_404_when_task_missing(self):
        service, repo = _make_service()
        repo.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            service.add_assignee(1, uuid4(), "Extra", None, "Actor")
        assert exc.value.status_code == 404


class TestRemoveAssignee:
    def test_success(self):
        service, repo = _make_service()
        repo.get.return_value = _task(1)
        admin_id = uuid4()
        assignee = CrmTaskAssignee(id=1, task_id=1, admin_id=admin_id, admin_display="Extra")
        repo.get_assignee.return_value = assignee
        repo.list_link_ids.return_value = []
        repo.list_assignees.return_value = []

        service.remove_assignee(1, admin_id, None, "Actor")

        repo.delete_assignee.assert_called_once_with(assignee)
        assert repo.add_activity.call_args.args[0].action == "unassign_extra"

    def test_404_when_not_found(self):
        service, repo = _make_service()
        repo.get.return_value = _task(1)
        repo.get_assignee.return_value = None
        with pytest.raises(HTTPException) as exc:
            service.remove_assignee(1, uuid4(), None, "Actor")
        assert exc.value.status_code == 404

    def test_404_when_task_missing(self):
        service, repo = _make_service()
        repo.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            service.remove_assignee(1, uuid4(), None, "Actor")
        assert exc.value.status_code == 404


class TestListAssignees:
    def test_returns_repo_list(self):
        service, repo = _make_service()
        repo.get.return_value = _task(1)
        expected = [MagicMock(spec=CrmTaskAssignee)]
        repo.list_assignees.return_value = expected
        assert service.list_assignees(1) is expected

    def test_404_when_task_missing(self):
        service, repo = _make_service()
        repo.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            service.list_assignees(1)
        assert exc.value.status_code == 404


class TestTaskDTOIntegration:
    """Confirms CrmTaskDTO picks up the transient linked_task_ids /
    extra_assignees attributes that CrmService attaches to the ORM
    instance (they aren't mapped columns)."""

    def test_dto_reflects_attached_relations(self):
        from crm.dtos import CrmTaskDTO

        service, repo = _make_service()
        task = _task(1)
        # CrmTaskDTO requires these — populated by server_default/onupdate
        # in the real DB, but a bare in-memory instance has none of that.
        task.description = ""
        task.labels = []
        task.sort_order = 0
        task.created_at = datetime.datetime.now(datetime.UTC)
        task.updated_at = datetime.datetime.now(datetime.UTC)
        repo.get.return_value = task
        repo.get_assignee.return_value = None
        admin_id = uuid4()
        repo.list_link_ids.return_value = [7, 8]
        repo.list_assignees.return_value = [
            CrmTaskAssignee(id=1, task_id=1, admin_id=admin_id, admin_display="Extra")
        ]

        result = service.add_assignee(1, admin_id, "Extra", None, "Actor")
        dto = CrmTaskDTO.model_validate(result)

        assert dto.linked_task_ids == [7, 8]
        assert len(dto.extra_assignees) == 1
        assert dto.extra_assignees[0].id == admin_id
        assert dto.extra_assignees[0].display == "Extra"
