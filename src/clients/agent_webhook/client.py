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

    def _task_payload(self, task: CrmTask) -> dict:
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

    def notify_task_assigned(self, task: CrmTask) -> None:
        if not self._settings.enabled or not self._settings.url:
            return
        try:
            httpx.post(
                f"{self._settings.url}/webhooks/crm-task-assigned",
                json=self._task_payload(task),
                headers={"X-Webhook-Secret": self._settings.secret},
                timeout=5.0,
            )
        except Exception:
            logger.exception(
                "Failed to notify agent executor of CRM task %s", task.id
            )

    def notify_board_event(
        self, event_type: str, task: CrmTask | None, change: dict | None = None
    ) -> None:
        """Generic board-change event (create/move/edit/delete). The
        executor uses these to stop a running session when its task is
        pulled back to «Не начато», and to start the next queued task
        when the «В работе» column frees up."""
        if not self._settings.enabled or not self._settings.url:
            return
        try:
            httpx.post(
                f"{self._settings.url}/webhooks/crm-event",
                json={
                    "type": event_type,
                    "task": self._task_payload(task) if task is not None else None,
                    "change": change or {},
                },
                headers={"X-Webhook-Secret": self._settings.secret},
                timeout=5.0,
            )
        except Exception:
            logger.exception("Failed to send board event %s", event_type)
