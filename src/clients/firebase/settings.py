from pydantic import BaseModel, Field


class FirebaseSettings(BaseModel):
    """Настройки Firebase Cloud Messaging."""

    enabled: bool = Field(
        default=False,
        description="Включает/выключает отправку push-уведомлений через FCM",
    )
    credentials_path: str | None = Field(
        default=None,
        description="Путь к сервисному ключу Firebase",
    )
    default_title: str = Field(
        default="Новые ежедневные задания уже ждут тебя!",
        description="Заголовок уведомления по умолчанию",
    )
    default_body: str = Field(
        default="Открывай приложение Lumi и решай свежий тест!",
        description="Текст уведомления по умолчанию",
    )
    batch_send_size: int = Field(
        default=500,
        ge=1,
        le=500,
        description="Размер мультикаста при отправке через FCM (макс. 500)",
    )
    fetch_chunk_size: int = Field(
        default=2000,
        ge=100,
        description="Размер пачки токенов, читаемой из базы",
    )
    timezone: str = Field(
        default="Asia/Almaty",
        description="Таймзона для ежедневных уведомлений",
    )
    notification_hour: int = Field(
        default=9,
        ge=0,
        le=23,
        description="Час отправки уведомления (по таймзоне)",
    )
    notification_minute: int = Field(
        default=0,
        ge=0,
        le=59,
        description="Минута отправки уведомления",
    )
