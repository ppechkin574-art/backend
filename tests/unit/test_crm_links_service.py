"""Unit tests for CrmService's task-linking ("связано с") methods.

CrmRepository is mocked out. The symmetric link is stored as two rows
(task->linked and linked->task); these tests pin that both rows get
created/removed together, and that self-links + duplicate links are
rejected.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from crm.models import CrmTask, CrmTaskLink
from crm.service import CrmService


def _make_service(repo=None):
    if repo is None:
        repo = MagicMock()
    return CrmService(repo), repo


def _task(task_id: int) -> CrmTask:
    return CrmTask(id=task_id, title=f"Task {task_id}", status="todo", priority="mid")


class TestAddLink:
    def test_success_creates_both_directions(self):
        service, repo = _make_service()
        repo.get.side_effect = lambda tid: _task(tid)
        repo.get_link.return_value = None
        repo.list_link_ids.return_value = [2]
        repo.list_assignees.return_value = []

        task = service.add_link(1, 2, None, "Admin")

        assert repo.add_link.call_count == 2
        first_call, second_call = repo.add_link.call_args_list
        assert (first_call.args[0].task_id, first_call.args[0].linked_task_id) == (1, 2)
        assert (second_call.args[0].task_id, second_call.args[0].linked_task_id) == (2, 1)

        repo.add_activity.assert_called_once()
        assert repo.add_activity.call_args.args[0].action == "link"
        assert task.linked_task_ids == [2]

    def test_self_link_rejected(self):
        service, repo = _make_service()
        with pytest.raises(HTTPException) as exc:
            service.add_link(1, 1, None, "Admin")
        assert exc.value.status_code == 400
        repo.get.assert_not_called()

    def test_404_when_task_missing(self):
        service, repo = _make_service()
        repo.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            service.add_link(1, 2, None, "Admin")
        assert exc.value.status_code == 404

    def test_404_when_linked_task_missing(self):
        service, repo = _make_service()
        repo.get.side_effect = [_task(1), None]
        with pytest.raises(HTTPException) as exc:
            service.add_link(1, 2, None, "Admin")
        assert exc.value.status_code == 404

    def test_duplicate_link_rejected(self):
        service, repo = _make_service()
        repo.get.side_effect = lambda tid: _task(tid)
        repo.get_link.return_value = CrmTaskLink(id=1, task_id=1, linked_task_id=2)
        with pytest.raises(HTTPException) as exc:
            service.add_link(1, 2, None, "Admin")
        assert exc.value.status_code == 400
        repo.add_link.assert_not_called()


class TestRemoveLink:
    def test_success_removes_both_directions(self):
        service, repo = _make_service()
        repo.get.return_value = _task(1)
        forward = CrmTaskLink(id=1, task_id=1, linked_task_id=2)
        reverse = CrmTaskLink(id=2, task_id=2, linked_task_id=1)
        repo.get_link.side_effect = [forward, reverse]
        repo.list_link_ids.return_value = []
        repo.list_assignees.return_value = []

        service.remove_link(1, 2, None, "Admin")

        repo.delete_link.assert_any_call(forward)
        repo.delete_link.assert_any_call(reverse)
        assert repo.delete_link.call_count == 2
        assert repo.add_activity.call_args.args[0].action == "unlink"

    def test_404_when_link_missing(self):
        service, repo = _make_service()
        repo.get.return_value = _task(1)
        repo.get_link.return_value = None
        with pytest.raises(HTTPException) as exc:
            service.remove_link(1, 2, None, "Admin")
        assert exc.value.status_code == 404
        repo.delete_link.assert_not_called()

    def test_404_when_task_missing(self):
        service, repo = _make_service()
        repo.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            service.remove_link(1, 2, None, "Admin")
        assert exc.value.status_code == 404


class TestListLinks:
    def test_returns_ids(self):
        service, repo = _make_service()
        repo.get.return_value = _task(1)
        repo.list_link_ids.return_value = [2, 3]
        assert service.list_links(1) == [2, 3]

    def test_404_when_task_missing(self):
        service, repo = _make_service()
        repo.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            service.list_links(1)
        assert exc.value.status_code == 404
