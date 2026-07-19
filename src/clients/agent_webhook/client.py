import logging

import httpx

from clients.agent_webhook.settings import AgentWebhookSettings
from crm.models import CrmTask

logger = logging.getLogger(__name__)


class AgentWebhookClient:
    """Notifies the 24/7 agent's executor service about CRM board changes.
    Fire-and-forget: failures are logged, never raised — a down executor
    must not break the CRM feature itself."""

    def __init__(self, settings: AgentWebhookSettings):
        self._settings = settings

    def task_payload(self, task: CrmTask) -> dict:
        """Snapshot the task NOW (pre-commit, ORM object alive) — the
        actual send happens post-commit via send_*, when a deleted task's
        ORM object would no longer be readable."""
        return {
            "task_id": task.id,
            "title": task.title,
            "description": task.description,
            "status": task.status,
            "priority": task.priority,
            "labels": task.labels,
            "assignee_admin_id": (
                str(task.assignee_admin_id) if task.assignee_admin_id else None
            ),
            "due_date": task.due_date.isoformat() if task.due_date else None,
        }

    def send_task_assigned(self, payload: dict) -> None:
        if not self._settings.enabled or not self._settings.url:
            return
        try:
            httpx.post(
                f"{self._settings.url}/webhooks/crm-task-assigned",
                json=payload,
                headers={"X-Webhook-Secret": self._settings.secret},
                timeout=5.0,
            )
        except Exception:
            logger.exception(
                "Failed to notify agent executor of CRM task %s",
                payload.get("task_id"),
            )

    def send_board_event(self, event: dict) -> None:
        """Generic board-change event (create/move/edit/delete). The
        executor uses these to stop a running session when its task is
        pulled back to «Не начато», and to start the next queued task
        when the «В работе» column frees up."""
        if not self._settings.enabled or not self._settings.url:
            return
        try:
            httpx.post(
                f"{self._settings.url}/webhooks/crm-event",
                json=event,
                headers={"X-Webhook-Secret": self._settings.secret},
                timeout=5.0,
            )
        except Exception:
            logger.exception("Failed to send board event %s", event.get("type"))
