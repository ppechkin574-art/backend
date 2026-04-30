import io
import logging
from typing import Protocol

from minio import Minio

from clients.media_storage.exceptions import MediaStorageError
from clients.media_storage.settings import MinioSettings


class MediaStorageClientInterface(Protocol):
    def save(self, name: str, content: io.BytesIO) -> None:
        """
        Save file.

        Args:
            name: File name.
            content: File content.

        Raises:
            MediaStorageError: Failed to save file.
        """
        raise NotImplementedError

    def link(self, name: str) -> str:
        """
        Create link to download file.

        Args:
            name: File name.

        Raises:
            MediaStorageError: Failed to create link.

        Returns:
            str: File link.
        """
        raise NotImplementedError


class MediaStorageClientMinio:
    def __init__(self, settings: MinioSettings) -> None:
        self._client = Minio(settings.endpoint, settings.access_key, settings.secret_key, secure=False)
        self._bucket = settings.bucket
        self._expires = settings.expires

    def save(self, name: str, content: io.BytesIO) -> None:
        try:
            self._client.put_object(self._bucket, name, content, content.getbuffer().nbytes)
        except Exception as e:
            logging.exception("Failed to save media (%s): %s", name, e)
            raise MediaStorageError from e

    def link(self, name: str) -> str:
        try:
            return self._client.presigned_get_object(self._bucket, name, expires=self._expires)
        except Exception as e:
            logging.exception("Failed to get link for media(%s): %s", name, e)
            raise MediaStorageError from e
