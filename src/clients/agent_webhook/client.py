import logging

import httpx

from clients.agent_webhook.settings import AgentWebhookSettings
from crm.models import CrmTask

logger = logging.getLogger(__name__)


class AgentWebhookClient:
    """Notifies the 24/7 agent's executor service when a CRM task is
    assigned to the agent. Fire-and-forget: failures are logged, never
    raised — a down or not-yet-built executor must not break the CRM
    feature itself."""

    def __init__(self, settings: AgentWebhookSettings):
        self._settings = settings

    def notify_task_assigned(self, task: CrmTask) -> None:
        if not self._settings.enabled or not self._settings.url:
            return
        try:
            httpx.post(
                f"{self._settings.url}/webhooks/crm-task-assigned",
                json={
                    "task_id": task.id,
                    "title": task.title,
                    "description": task.description,
                    "priority": task.priority,
                    "labels": task.labels,
                    "due_date": task.due_date.isoformat() if task.due_date else None,
                },
                headers={"X-Webhook-Secret": self._settings.secret},
                timeout=5.0,
            )
        except Exception:
            logger.exception(
                "Failed to notify agent executor of CRM task %s", task.id
            )
