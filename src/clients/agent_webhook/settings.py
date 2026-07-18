from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentWebhookSettings(BaseSettings):
    """Webhook dispatch to the 24/7 agent's executor service, fired when a
    CRM task is assigned to the agent's Keycloak account. All fields have
    defaults so the feature stays off until the executor service exists —
    ``enabled=False`` (or a blank ``url``) is a safe no-op.
    """

    model_config = SettingsConfigDict(extra="ignore")

    enabled: bool = False
    url: str = ""
    secret: str = ""
    agent_admin_id: str = ""
