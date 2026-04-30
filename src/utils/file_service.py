import io
import logging
import os
import uuid

from fastapi import HTTPException, UploadFile
from PIL import Image

logger = logging.getLogger(__name__)


class FileService:
    def __init__(self, upload_base_dir: str = "/app/uploads", file_base_url: str | None = None):
        self.upload_base_dir = upload_base_dir

        if file_base_url is None:
            file_base_url = os.getenv("FILE_BASE_URL", "")
            logger.info("FileService: Got FILE_BASE_URL from environment: '%s'", file_base_url)

        self.file_base_url = file_base_url.rstrip("/") if file_base_url else ""

        self.avatars_dir = os.path.join(upload_base_dir, "avatars")
        self.subjects_dir = os.path.join(upload_base_dir, "subjects")
        os.makedirs(self.avatars_dir, exist_ok=True)
        os.makedirs(self.subjects_dir, exist_ok=True)

    async def save_avatar(self, user_id: str, avatar_file: UploadFile) -> str:
        try:
            if not avatar_file.content_type.startswith("image/"):
                raise HTTPException(status_code=400, detail="File must be an image")

            contents = await avatar_file.read()
            logger.info("  - file size: %s bytes", len(contents))

            if len(contents) > 5 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="File too large. Max 5MB")

            processed_image = await self._process_image(contents)

            file_extension = "jpg"
            filename = f"{user_id}_{uuid.uuid4().hex}.{file_extension}"
            file_path = os.path.join(self.avatars_dir, filename)

            with open(file_path, "wb") as buffer:
                buffer.write(processed_image)

            logger.info("Avatar saved for user %s: %s", user_id, filename)
            return filename

        except Exception as e:
            logger.exception("Error saving avatar for user %s: %s", user_id, str(e))
            raise HTTPException(status_code=500, detail="Failed to save avatar") from e

    async def save_subject_image(self, image_file: UploadFile) -> str:
        try:
            if not image_file.content_type.startswith("image/"):
                raise HTTPException(status_code=400, detail="File must be an image")

            contents = await image_file.read()
            if len(contents) > 5 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="File too large. Max 5MB")

            processed_image = await self._process_image(contents)

            filename = f"subject_{uuid.uuid4().hex}.jpg"
            file_path = os.path.join(self.subjects_dir, filename)

            with open(file_path, "wb") as buffer:
                buffer.write(processed_image)

            logger.info("Subject image saved: %s", filename)
            return filename

        except Exception as e:
            logger.exception("Error saving subject image: %s", str(e))
            raise HTTPException(status_code=500, detail="Failed to save image") from e

    async def _process_image(self, image_data: bytes) -> bytes:
        try:
            image = Image.open(io.BytesIO(image_data))

            if image.mode in ("RGBA", "LA", "P"):
                image = image.convert("RGB")

            image.thumbnail((500, 500), Image.Resampling.LANCZOS)

            output = io.BytesIO()
            image.save(output, format="JPEG", quality=85, optimize=True)

            return output.getvalue()

        except Exception as e:
            logger.exception("Error processing image: %s", str(e))
            raise HTTPException(status_code=400, detail="Invalid image file") from e

    def delete_avatar(self, filename: str) -> bool:
        try:
            file_path = os.path.join(self.avatars_dir, filename)
            if os.path.exists(file_path):
                os.remove(file_path)
                return True
            return False
        except Exception as e:
            logger.exception("Error deleting avatar %s: %s", filename, str(e))
            return False

    def delete_subject_image(self, filename: str) -> bool:
        try:
            file_path = os.path.join(self.subjects_dir, filename)
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info("Subject image deleted: %s", filename)
                return True
            return False
        except Exception as e:
            logger.exception("Error deleting subject image %s: %s", filename, str(e))
            return False

    def get_avatar_url(self, filename: str) -> str:
        if not filename:
            return ""

        if self.file_base_url:
            return f"{self.file_base_url}/uploads/avatars/{filename}"
        else:
            return f"/uploads/avatars/{filename}"

    def get_subject_image_url(self, image_path: str) -> str | None:
        if not image_path:
            return None

        if image_path.startswith("/"):
            return f"{self.file_base_url}/uploads{image_path}"
        else:
            return f"{self.file_base_url}/uploads/subjects/{image_path}"
