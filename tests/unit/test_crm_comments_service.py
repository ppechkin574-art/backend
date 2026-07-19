"""Unit tests for CrmService's comment-thread methods.

This is a separate feed from the existing ``update_crm_task(comment=...)``
agent tool (which appends to ``description``) — these tests only cover
the new ``CrmTaskComment`` entity/endpoints.
"""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from crm.dtos import CrmCommentCreateDTO
from crm.models import CrmTask, CrmTaskComment
from crm.service import CrmService


def _make_service(repo=None):
    if repo is None:
        repo = MagicMock()
    return CrmService(repo), repo


def _task(task_id: int = 1) -> CrmTask:
    return CrmTask(id=task_id, title="Task", status="todo", priority="mid")


class TestAddComment:
    def test_success(self):
        service, repo = _make_service()
        task = _task(1)
        repo.get.return_value = task

        def fake_add(comment):
            comment.id = 10
            return comment

        repo.add_comment.side_effect = fake_add

        actor_id = uuid4()
        comment = service.add_comment(1, "Please review this by EOD", actor_id, "Admin One")

        assert comment.task_id == 1
        assert comment.text == "Please review this by EOD"
        assert comment.admin_id == actor_id
        assert comment.admin_display == "Admin One"

        repo.add_activity.assert_called_once()
        logged = repo.add_activity.call_args.args[0]
        assert logged.action == "comment"
        assert logged.details == {"comment_id": 10}

    def test_404_when_task_missing(self):
        service, repo = _make_service()
        repo.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            service.add_comment(1, "hello", None, "Admin")
        assert exc.value.status_code == 404
        repo.add_comment.assert_not_called()

    def test_anonymous_actor_allowed(self):
        """admin_id is nullable — mirrors CrmActivity's own admin_id
        nullability for system/anonymous actions."""
        service, repo = _make_service()
        repo.get.return_value = _task(1)
        repo.add_comment.side_effect = lambda c: c
        comment = service.add_comment(1, "note", None, "System")
        assert comment.admin_id is None


class TestListComments:
    def test_returns_repo_list(self):
        service, repo = _make_service()
        repo.get.return_value = _task(1)
        expected = [MagicMock(spec=CrmTaskComment)]
        repo.list_comments.return_value = expected
        assert service.list_comments(1) is expected

    def test_404_when_task_missing(self):
        service, repo = _make_service()
        repo.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            service.list_comments(1)
        assert exc.value.status_code == 404


class TestCommentCreateDTOValidation:
    def test_rejects_empty_text(self):
        with pytest.raises(ValidationError):
            CrmCommentCreateDTO(text="")

    def test_rejects_text_over_max_length(self):
        with pytest.raises(ValidationError):
            CrmCommentCreateDTO(text="x" * 4001)

    def test_accepts_text_at_max_length(self):
        dto = CrmCommentCreateDTO(text="x" * 4000)
        assert len(dto.text) == 4000
