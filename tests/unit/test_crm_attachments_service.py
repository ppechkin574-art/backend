"""Unit tests for CrmService's file-attachment methods.

The MediaStorageClientInterface (S3/MinIO) and CrmRepository are both
mocked out — pure logic tests for validation (size cap, blocked
extensions, dangerous magic bytes, path-traversal-safe filenames) and
for the create/list/delete/url flow.
"""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from clients.media_storage.exceptions import MediaStorageError
from crm.models import CrmTask, CrmTaskAttachment
from crm.service import CrmService


_UNSET = object()


def _make_service(repo=None, media_storage=_UNSET):
    if repo is None:
        repo = MagicMock()
    if media_storage is _UNSET:
        media_storage = MagicMock()
    return CrmService(repo, media_storage=media_storage), repo, media_storage


def _task(task_id: int = 1) -> CrmTask:
    return CrmTask(id=task_id, title="Some task", status="todo", priority="mid")


class TestAddAttachment:
    def test_success_saves_to_storage_and_logs(self):
        service, repo, storage = _make_service()
        task = _task(1)
        repo.get.return_value = task

        def fake_add(attachment):
            attachment.id = 42
            return attachment

        repo.add_attachment.side_effect = fake_add

        actor_id = uuid4()
        attachment = service.add_attachment(
            task_id=1,
            filename="report.pdf",
            content_type="application/pdf",
            content=b"%PDF-1.4 fake content",
            actor_id=actor_id,
            actor_display="Admin One",
        )

        assert attachment.filename == "report.pdf"
        assert attachment.task_id == 1
        assert attachment.size == len(b"%PDF-1.4 fake content")
        assert attachment.uploaded_by == actor_id
        assert attachment.uploaded_by_display == "Admin One"

        # Saved under the crm-attachments/{task_id}/ prefix.
        storage.save.assert_called_once()
        object_name = storage.save.call_args.args[0]
        assert object_name.startswith("crm-attachments/1/")
        assert object_name.endswith("_report.pdf")

        # Activity logged with action "attach".
        repo.add_activity.assert_called_once()
        logged = repo.add_activity.call_args.args[0]
        assert logged.action == "attach"

    def test_404_when_task_missing(self):
        service, repo, _ = _make_service()
        repo.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            service.add_attachment(1, "a.txt", "text/plain", b"data", None, "Admin")
        assert exc.value.status_code == 404

    def test_empty_file_rejected(self):
        service, repo, _ = _make_service()
        repo.get.return_value = _task()
        with pytest.raises(HTTPException) as exc:
            service.add_attachment(1, "a.txt", "text/plain", b"", None, "Admin")
        assert exc.value.status_code == 400

    def test_oversized_file_rejected(self):
        service, repo, _ = _make_service()
        repo.get.return_value = _task()
        too_big = b"x" * (service.MAX_ATTACHMENT_SIZE_BYTES + 1)
        with pytest.raises(HTTPException) as exc:
            service.add_attachment(1, "a.txt", "text/plain", too_big, None, "Admin")
        assert exc.value.status_code == 400
        assert "20" in exc.value.detail

    @pytest.mark.parametrize(
        "filename",
        [
            "virus.exe",
            "script.sh",
            "payload.bat",
            "installer.msi",
            "evil.js",
            "macro.jar",
            "hack.ps1",
        ],
    )
    def test_blocked_extensions_rejected(self, filename):
        service, repo, _ = _make_service()
        repo.get.return_value = _task()
        with pytest.raises(HTTPException) as exc:
            service.add_attachment(1, filename, "application/octet-stream", b"data", None, "Admin")
        assert exc.value.status_code == 400

    def test_renamed_executable_rejected_via_magic_bytes(self):
        """A Windows PE renamed to .pdf must still be blocked — the
        extension alone isn't trusted."""
        service, repo, _ = _make_service()
        repo.get.return_value = _task()
        pe_header = b"MZ\x90\x00\x03\x00\x00\x00fakestuff"
        with pytest.raises(HTTPException) as exc:
            service.add_attachment(1, "innocent.pdf", "application/pdf", pe_header, None, "Admin")
        assert exc.value.status_code == 400

    def test_shebang_script_rejected_regardless_of_extension(self):
        service, repo, _ = _make_service()
        repo.get.return_value = _task()
        script = b"#!/bin/bash\nrm -rf /"
        with pytest.raises(HTTPException) as exc:
            service.add_attachment(1, "notes.txt", "text/plain", script, None, "Admin")
        assert exc.value.status_code == 400

    def test_path_traversal_filename_sanitized(self):
        service, repo, storage = _make_service()
        repo.get.return_value = _task()
        repo.add_attachment.side_effect = lambda a: a

        attachment = service.add_attachment(
            1, "../../etc/passwd", "text/plain", b"data", None, "Admin"
        )
        assert "/" not in attachment.filename
        assert ".." not in attachment.filename
        object_name = storage.save.call_args.args[0]
        assert ".." not in object_name

    def test_storage_error_raises_500(self):
        service, repo, storage = _make_service()
        repo.get.return_value = _task()
        storage.save.side_effect = MediaStorageError("boom")
        with pytest.raises(HTTPException) as exc:
            service.add_attachment(1, "ok.txt", "text/plain", b"data", None, "Admin")
        assert exc.value.status_code == 500

    def test_missing_media_storage_raises_500(self):
        service, repo, _ = _make_service(media_storage=None)
        repo.get.return_value = _task()
        with pytest.raises(HTTPException) as exc:
            service.add_attachment(1, "ok.txt", "text/plain", b"data", None, "Admin")
        assert exc.value.status_code == 500


class TestListAttachments:
    def test_returns_repo_list(self):
        service, repo, _ = _make_service()
        repo.get.return_value = _task()
        expected = [MagicMock(spec=CrmTaskAttachment)]
        repo.list_attachments.return_value = expected
        assert service.list_attachments(1) is expected

    def test_404_when_task_missing(self):
        service, repo, _ = _make_service()
        repo.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            service.list_attachments(1)
        assert exc.value.status_code == 404


class TestRemoveAttachment:
    def test_success_removes_from_storage_and_db(self):
        service, repo, storage = _make_service()
        task = _task(1)
        repo.get.return_value = task
        attachment = CrmTaskAttachment(
            id=5, task_id=1, object_name="crm-attachments/1/x_a.txt", filename="a.txt", size=1
        )
        repo.get_attachment.return_value = attachment

        service.remove_attachment(1, 5, None, "Admin")

        storage.remove.assert_called_once_with("crm-attachments/1/x_a.txt")
        repo.delete_attachment.assert_called_once_with(attachment)
        repo.add_activity.assert_called_once()
        assert repo.add_activity.call_args.args[0].action == "unattach"

    def test_404_when_attachment_missing(self):
        service, repo, _ = _make_service()
        repo.get.return_value = _task(1)
        repo.get_attachment.return_value = None
        with pytest.raises(HTTPException) as exc:
            service.remove_attachment(1, 999, None, "Admin")
        assert exc.value.status_code == 404

    def test_404_when_attachment_belongs_to_other_task(self):
        service, repo, _ = _make_service()
        repo.get.return_value = _task(1)
        other_task_attachment = CrmTaskAttachment(
            id=5, task_id=2, object_name="x", filename="a.txt", size=1
        )
        repo.get_attachment.return_value = other_task_attachment
        with pytest.raises(HTTPException) as exc:
            service.remove_attachment(1, 5, None, "Admin")
        assert exc.value.status_code == 404

    def test_storage_removal_failure_does_not_block_db_delete(self):
        """If S3 removal fails we still drop the DB row — an orphan S3
        object is an acceptable trade-off vs. a stuck attachment row."""
        service, repo, storage = _make_service()
        repo.get.return_value = _task(1)
        attachment = CrmTaskAttachment(
            id=5, task_id=1, object_name="crm-attachments/1/x_a.txt", filename="a.txt", size=1
        )
        repo.get_attachment.return_value = attachment
        storage.remove.side_effect = MediaStorageError("boom")

        service.remove_attachment(1, 5, None, "Admin")  # should not raise
        repo.delete_attachment.assert_called_once_with(attachment)


class TestAttachmentUrl:
    def test_builds_presigned_url(self):
        service, _, storage = _make_service()
        storage.link.return_value = "https://minio/example"
        attachment = CrmTaskAttachment(id=1, task_id=1, object_name="obj", filename="a", size=1)
        assert service.attachment_url(attachment) == "https://minio/example"

    def test_returns_empty_string_when_no_storage(self):
        service, _, _ = _make_service(media_storage=None)
        attachment = CrmTaskAttachment(id=1, task_id=1, object_name="obj", filename="a", size=1)
        assert service.attachment_url(attachment) == ""

    def test_returns_empty_string_on_storage_error(self):
        service, _, storage = _make_service()
        storage.link.side_effect = MediaStorageError("boom")
        attachment = CrmTaskAttachment(id=1, task_id=1, object_name="obj", filename="a", size=1)
        assert service.attachment_url(attachment) == ""
