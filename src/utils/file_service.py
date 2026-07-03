import io
import logging
import uuid

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps

# Register HEIC/HEIF decoder with Pillow (iPhone photos default to HEIC).
# image_picker on iOS usually converts to JPEG on device, but the
# Android counterpart and any third-party uploader can send HEIC directly.
# Soft-failing the import lets the service still run if pillow-heif isn't
# installed (e.g. in unit-test envs that mock the storage layer).
try:
    import pillow_heif  # type: ignore[import-untyped]

    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover
    logger_warning = logging.getLogger(__name__)
    logger_warning.warning(
        "pillow-heif not installed — HEIC uploads will be rejected at PIL decode"
    )

from clients.media_storage.client import MediaStorageClientInterface
from clients.media_storage.exceptions import MediaStorageError

logger = logging.getLogger(__name__)

# Magic-byte signatures for image formats we accept. Trusting the
# multipart `Content-Type` header is unsafe (client-controlled); these
# are sniffed from the first bytes of the actual file body. JPEG/PNG/
# GIF/WebP cover everything image_picker emits, plus HEIC for the
# iPhone-direct case.
_IMAGE_MAGIC_PREFIXES: tuple[bytes, ...] = (
    b"\xff\xd8\xff",                # JPEG
    b"\x89PNG\r\n\x1a\n",           # PNG
    b"GIF87a",                       # GIF87a
    b"GIF89a",                       # GIF89a
    b"BM",                           # BMP
)
# WebP and HEIC live inside RIFF/ISO-BMFF containers — both keep their
# brand tag at byte offset 4, so the sniff matches the brand specifically
# (not just `RIFF`/`ftyp`) to avoid greenlighting an arbitrary container.
_IMAGE_BRAND_AT_OFFSET_4: tuple[bytes, ...] = (
    b"WEBP",                         # RIFF/...WEBP
    b"ftypheic", b"ftypheix",        # HEIC variants
    b"ftypmif1", b"ftypmsf1",        # HEIF variants
    b"ftypavif",                     # AVIF
)

# Cap on decoded pixel count to defuse a decompression bomb: a 100KB
# malicious PNG can describe a 50000x50000 image that expands to ~7.5GB
# in RAM during PIL decode. 25M pixels accommodates 5000x5000 source
# images (well over what `image_picker.maxWidth=1024` ever produces)
# while keeping peak RAM in the tens-of-MB range.
_MAX_DECODED_PIXELS = 25_000_000


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
    MASCOT_PREFIX = "mascot"
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
        """Загружает картинку предмета в S3. Возвращает имя файла.

        В отличие от аватаров, иконки предметов могут быть прозрачными
        силуэтами — клиент тонирует их в `Colors.white` через
        `Image.network(color: ...)`. Поэтому сохраняем PNG c альфа-каналом,
        если входная картинка имеет прозрачность. Иначе — JPEG как раньше.
        """
        contents = await self._read_validated_image(image_file)
        processed, ext = await self._process_image_keep_alpha(contents)

        filename = f"subject_{uuid.uuid4().hex}.{ext}"
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

    async def save_mascot_image(self, image_file: UploadFile) -> str:
        """Загружает PNG маскота в S3. Сохраняет прозрачность. Возвращает имя файла."""
        contents = await self._read_validated_image(image_file)
        processed, ext = await self._process_image_keep_alpha(contents)

        filename = f"mascot_{uuid.uuid4().hex}.{ext}"
        object_name = f"{self.MASCOT_PREFIX}/{filename}"

        try:
            self._storage.save(object_name, io.BytesIO(processed))
        except MediaStorageError as e:
            logger.exception("Failed to save mascot image")
            raise HTTPException(status_code=500, detail="Failed to save image") from e

        logger.info("Mascot image saved: %s", object_name)
        return filename

    def get_mascot_image_url(self, filename: str) -> str:
        """Presigned URL для маскота."""
        if not filename:
            return ""
        if filename.startswith(("http://", "https://")):
            return filename
        try:
            return self._storage.link(f"{self.MASCOT_PREFIX}/{self._extract_filename(filename)}")
        except MediaStorageError as e:
            logger.warning("Failed to build mascot image URL for %s: %s", filename, e)
            return ""

    def delete_mascot_image(self, filename: str) -> bool:
        return self._delete_object(f"{self.MASCOT_PREFIX}/{self._extract_filename(filename)}")

    def get_avatar_url(self, filename: str) -> str:
        """Presigned URL для отдачи аватара клиенту.

        Принимает имя файла ИЛИ старый presigned URL (legacy-данные, когда
        URL хранился напрямую в Keycloak). В обоих случаях генерируется
        свежий presigned URL, чтобы истёкшие ссылки не ломали аватарки.
        """
        if not filename:
            return ""
        bare = self._extract_filename(filename)
        if not bare:
            return ""
        try:
            return self._storage.link(f"{self.AVATAR_PREFIX}/{bare}")
        except MediaStorageError as e:
            logger.warning("Failed to build avatar URL for %s: %s", filename, e)
            return ""

    def get_subject_image_url(self, image_path: str) -> str:
        """Presigned URL для отдачи картинки предмета.

        Принимает:
          - имя файла (subject_xxx.jpg) → генерируется presigned URL в S3
          - устаревший относительный путь /images/subjects/foo.jpg → presigned по имени файла
          - абсолютный URL (http(s)://...) → отдаётся как есть, без обращения к S3
            (это нужно потому что в дампе БД у Романа image хранится как
            абсолютный URL на legacy-CDN, и каждый presigned-запрос
            к MinIO в этом случае был бы лишним сетевым вызовом)

        Возвращает пустую строку, если путь пуст или MinIO не смог сгенерить URL
        (например, файл ещё не залит в bucket — см. TECH_DEBT.md п.112).
        Симметрично get_avatar_url, чтобы клиенты не получали null и не падали на
        парсинге не-nullable String.
        """
        if not image_path:
            return ""
        if image_path.startswith(("http://", "https://")):
            return image_path
        try:
            return self._storage.link(f"{self.SUBJECT_PREFIX}/{self._extract_filename(image_path)}")
        except MediaStorageError as e:
            logger.warning("Failed to build subject image URL for %s: %s", image_path, e)
            return ""

    async def _read_validated_image(self, file: UploadFile) -> bytes:
        # Cheap header check first to short-circuit obvious mismatches —
        # the magic-byte sniff below is the actual source of truth.
        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="File must be an image")

        contents = await file.read()
        if len(contents) > self.MAX_FILE_SIZE_BYTES:
            raise HTTPException(status_code=400, detail="File too large. Max 5MB")

        if not self._sniff_image_magic(contents):
            raise HTTPException(
                status_code=400,
                detail="Unsupported or malformed image file",
            )
        return contents

    @staticmethod
    def _sniff_image_magic(data: bytes) -> bool:
        """Validate the first bytes against known image format
        signatures. Trusting the multipart Content-Type header is
        unsafe (client-controlled); a real magic-byte check stops
        polyglot / mis-labelled files from reaching PIL."""
        if len(data) < 12:
            return False
        if data.startswith(_IMAGE_MAGIC_PREFIXES):
            return True
        # WebP / HEIC / AVIF: container brand sits at bytes 4..12.
        brand_region = data[4:16]
        return any(brand in brand_region for brand in _IMAGE_BRAND_AT_OFFSET_4)

    async def _process_image(self, image_data: bytes) -> bytes:
        try:
            image = Image.open(io.BytesIO(image_data))
            self._guard_dimensions(image)
            # Defense-in-depth: apply EXIF Orientation to pixels even if
            # the client already baked it. Covers any future client
            # (Android/web/integrations) sending raw camera JPEGs.
            image = ImageOps.exif_transpose(image)

            if image.mode in ("RGBA", "LA", "P"):
                image = image.convert("RGB")

            image.thumbnail(self.THUMBNAIL_SIZE, Image.Resampling.LANCZOS)

            output = io.BytesIO()
            image.save(output, format="JPEG", quality=self.JPEG_QUALITY, optimize=True)

            return output.getvalue()
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Error processing image: %s", e)
            raise HTTPException(status_code=400, detail="Invalid image file") from e

    async def _process_image_keep_alpha(self, image_data: bytes) -> tuple[bytes, str]:
        """Сохраняет PNG с альфа-каналом если у входа есть прозрачность,
        иначе сжимает в JPEG как обычный _process_image.

        Возвращает (bytes, extension) — расширение нужно вызывающему коду
        для построения имени файла в bucket.
        """
        try:
            image = Image.open(io.BytesIO(image_data))
            self._guard_dimensions(image)
            image = ImageOps.exif_transpose(image)
            has_alpha = image.mode in ("RGBA", "LA") or (
                image.mode == "P" and "transparency" in image.info
            )

            if has_alpha:
                image = image.convert("RGBA")
                image.thumbnail(self.THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                output = io.BytesIO()
                image.save(output, format="PNG", optimize=True)
                return output.getvalue(), "png"

            if image.mode != "RGB":
                image = image.convert("RGB")
            image.thumbnail(self.THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=self.JPEG_QUALITY, optimize=True)
            return output.getvalue(), "jpg"
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Error processing image: %s", e)
            raise HTTPException(status_code=400, detail="Invalid image file") from e

    @staticmethod
    def _guard_dimensions(image: Image.Image) -> None:
        """Block decompression-bomb inputs before they hit pixel-level
        operations. A 50000x50000 PNG can be 100KB on disk but expand
        to 7.5GB in RAM during PIL processing; the cheap pre-check
        rejects those at HTTP-400 instead of OOM-killing the worker."""
        width, height = image.size
        if width * height > _MAX_DECODED_PIXELS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Image too large: {width}x{height} exceeds "
                    f"{_MAX_DECODED_PIXELS:,} pixel limit"
                ),
            )

    def _delete_object(self, object_name: str) -> bool:
        try:
            self._storage.remove(object_name)
            return True
        except MediaStorageError as e:
            logger.warning("Failed to delete object %s: %s", object_name, e)
            return False

    @staticmethod
    def _extract_filename(value: str) -> str:
        """Берёт последний сегмент пути, убирая query string.

        Поддерживает все форматы:
        - "subject_xxx.jpg"                        → "subject_xxx.jpg"
        - "/images/subjects/abc.jpg"               → "abc.jpg"
        - "subjects/abc.jpg"                       → "abc.jpg"
        - "https://minio.../avatars/x.jpg?X-Amz-..." → "x.jpg"
        """
        from urllib.parse import urlparse
        path = urlparse(value).path or value
        return path.rstrip("/").split("/")[-1]
