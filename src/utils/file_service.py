import io
import logging
import uuid

from fastapi import HTTPException, UploadFile
from PIL import Image

from clients.media_storage.client import MediaStorageClientInterface
from clients.media_storage.exceptions import MediaStorageError

logger = logging.getLogger(__name__)


class FileService:
    """
    Хранение медиа-файлов в S3-совместимом storage (MinIO).

    Все файлы лежат в одном bucket, организация через префиксы:
        avatars/<user_id>_<uuid>.jpg
        subjects/<uuid>.jpg

    Раздача — через presigned URL (TTL задан в настройках MinIO).
    Локальный диск не используется — контейнеры backend могут масштабироваться.
    """

    AVATAR_PREFIX = "avatars"
    SUBJECT_PREFIX = "subjects"
    MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024
    THUMBNAIL_SIZE = (500, 500)
    JPEG_QUALITY = 85

    def __init__(self, media_storage: MediaStorageClientInterface):
        self._storage = media_storage

    async def save_avatar(self, user_id: str, avatar_file: UploadFile) -> str:
        """Загружает аватар пользователя в S3. Возвращает имя файла."""
        contents = await self._read_validated_image(avatar_file)
        processed = await self._process_image(contents)

        filename = f"{user_id}_{uuid.uuid4().hex}.jpg"
        object_name = f"{self.AVATAR_PREFIX}/{filename}"

        try:
            self._storage.save(object_name, io.BytesIO(processed))
        except MediaStorageError as e:
            logger.exception("Failed to save avatar for user %s", user_id)
            raise HTTPException(status_code=500, detail="Failed to save avatar") from e

        logger.info("Avatar saved: %s", object_name)
        return filename

    async def save_subject_image(self, image_file: UploadFile) -> str:
        """Загружает картинку предмета в S3. Возвращает имя файла."""
        contents = await self._read_validated_image(image_file)
        processed = await self._process_image(contents)

        filename = f"subject_{uuid.uuid4().hex}.jpg"
        object_name = f"{self.SUBJECT_PREFIX}/{filename}"

        try:
            self._storage.save(object_name, io.BytesIO(processed))
        except MediaStorageError as e:
            logger.exception("Failed to save subject image")
            raise HTTPException(status_code=500, detail="Failed to save image") from e

        logger.info("Subject image saved: %s", object_name)
        return filename

    def delete_avatar(self, filename: str) -> bool:
        """Удаляет аватар по имени файла. Возвращает True если удалили."""
        return self._delete_object(f"{self.AVATAR_PREFIX}/{self._extract_filename(filename)}")

    def delete_subject_image(self, filename: str) -> bool:
        """Удаляет картинку предмета по имени файла."""
        return self._delete_object(f"{self.SUBJECT_PREFIX}/{self._extract_filename(filename)}")

    def get_avatar_url(self, filename: str) -> str:
        """Presigned URL для отдачи аватара клиенту."""
        if not filename:
            return ""
        # Если уже абсолютный URL (например, при миграции с другого хранилища) — отдаём как есть
        if filename.startswith(("http://", "https://")):
            return filename
        try:
            return self._storage.link(f"{self.AVATAR_PREFIX}/{self._extract_filename(filename)}")
        except MediaStorageError as e:
            logger.warning("Failed to build avatar URL for %s: %s", filename, e)
            return ""

    def get_subject_image_url(self, image_path: str) -> str | None:
        """Presigned URL для отдачи картинки предмета.

        Принимает:
          - имя файла (subject_xxx.jpg) → генерируется presigned URL в S3
          - устаревший относительный путь /images/subjects/foo.jpg → presigned по имени файла
          - абсолютный URL (http(s)://...) → отдаётся как есть, без обращения к S3
            (это нужно потому что в дампе БД у Романа image хранится как
            "https://lumi-unt.kz/uploads/...", и каждый presigned-запрос
            к MinIO в этом случае был бы лишним сетевым вызовом)
        """
        if not image_path:
            return None
        if image_path.startswith(("http://", "https://")):
            return image_path
        try:
            return self._storage.link(f"{self.SUBJECT_PREFIX}/{self._extract_filename(image_path)}")
        except MediaStorageError as e:
            logger.warning("Failed to build subject image URL for %s: %s", image_path, e)
            return None

    async def _read_validated_image(self, file: UploadFile) -> bytes:
        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="File must be an image")

        contents = await file.read()
        if len(contents) > self.MAX_FILE_SIZE_BYTES:
            raise HTTPException(status_code=400, detail="File too large. Max 5MB")
        return contents

    async def _process_image(self, image_data: bytes) -> bytes:
        try:
            image = Image.open(io.BytesIO(image_data))

            if image.mode in ("RGBA", "LA", "P"):
                image = image.convert("RGB")

            image.thumbnail(self.THUMBNAIL_SIZE, Image.Resampling.LANCZOS)

            output = io.BytesIO()
            image.save(output, format="JPEG", quality=self.JPEG_QUALITY, optimize=True)

            return output.getvalue()
        except Exception as e:
            logger.exception("Error processing image: %s", e)
            raise HTTPException(status_code=400, detail="Invalid image file") from e

    def _delete_object(self, object_name: str) -> bool:
        try:
            self._storage.remove(object_name)
            return True
        except MediaStorageError as e:
            logger.warning("Failed to delete object %s: %s", object_name, e)
            return False

    @staticmethod
    def _extract_filename(value: str) -> str:
        """Берёт последний сегмент пути. Поддерживает обе формы:
        - "subject_xxx.jpg"            → "subject_xxx.jpg"
        - "/images/subjects/abc.jpg"   → "abc.jpg"
        - "subjects/abc.jpg"           → "abc.jpg"
        """
        return value.rstrip("/").split("/")[-1]
