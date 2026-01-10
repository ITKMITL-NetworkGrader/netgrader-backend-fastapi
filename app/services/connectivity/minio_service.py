import asyncio
import io
import logging
from datetime import timedelta
from pathlib import Path
from typing import AsyncIterator, BinaryIO, Dict, Optional, Union

from minio import Minio
from minio.error import S3Error

from app.core.config import config

logger = logging.getLogger(__name__)


class MinioConnectionError(Exception):
    """Raised when the MinIO client cannot be initialized."""


class MinioService:
    """Async-friendly wrapper around the MinIO Python client."""

    def __init__(
        self,
        endpoint: Optional[str] = None,
        port: Optional[int] = None,
        use_ssl: Optional[bool] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        bucket_name: Optional[str] = None,
        auto_create_bucket: bool = True,
    ) -> None:
        self.endpoint_host = endpoint or config.MINIO_ENDPOINT
        self.port = port if port is not None else config.MINIO_PORT
        self.use_ssl = config.MINIO_USE_SSL if use_ssl is None else use_ssl
        self.access_key = access_key or config.MINIO_ACCESS_KEY
        self.secret_key = secret_key or config.MINIO_SECRET_KEY
        self.bucket_name = bucket_name or config.MINIO_BUCKET_NAME or None
        self.auto_create_bucket = auto_create_bucket

        if ":" in self.endpoint_host or self.port is None:
            self._client_endpoint = self.endpoint_host
        else:
            self._client_endpoint = f"{self.endpoint_host}:{self.port}"

        self._client: Optional[Minio] = None
        self._client_lock = asyncio.Lock()

    async def _ensure_client(self) -> Minio:
        if self._client:
            return self._client

        needs_bucket_init = False
        async with self._client_lock:
            if not self._client:
                try:
                    self._client = Minio(
                        endpoint=self._client_endpoint,
                        access_key=self.access_key,
                        secret_key=self.secret_key,
                        secure=self.use_ssl,
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    logger.error("Failed to initialize MinIO client: %s", exc)
                    raise MinioConnectionError(str(exc)) from exc

                needs_bucket_init = bool(self.auto_create_bucket and self.bucket_name)

        if needs_bucket_init:
            try:
                await self.ensure_bucket(self.bucket_name)
            except S3Error:
                logger.exception("Failed to auto-create MinIO bucket '%s'", self.bucket_name)
                raise

        return self._client  # type: ignore[return-value]

    async def ensure_bucket(self, bucket_name: Optional[str]) -> bool:
        target_bucket = bucket_name or self.bucket_name
        if not target_bucket:
            raise ValueError("Bucket name must be provided")

        client = await self._ensure_client()
        exists = await asyncio.to_thread(client.bucket_exists, target_bucket)
        if not exists:
            logger.info("Creating MinIO bucket '%s'", target_bucket)
            await asyncio.to_thread(client.make_bucket, target_bucket)
        return True

    async def upload_file(
        self,
        object_name: str,
        file_path: Union[str, Path],
        bucket_name: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> str:
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {path}")

        target_bucket = bucket_name or self.bucket_name
        if not target_bucket:
            raise ValueError("Bucket name must be provided")

        client = await self._ensure_client()
        if self.auto_create_bucket:
            await self.ensure_bucket(target_bucket)

        logger.debug("Uploading '%s' to bucket '%s'", object_name, target_bucket)
        result = await asyncio.to_thread(
            client.fput_object,
            target_bucket,
            object_name,
            str(path),
            content_type=content_type,
            metadata=metadata,
        )
        return result.etag

    async def upload_data(
        self,
        object_name: str,
        data: Union[bytes, BinaryIO],
        length: Optional[int] = None,
        bucket_name: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> str:
        target_bucket = bucket_name or self.bucket_name
        if not target_bucket:
            raise ValueError("Bucket name must be provided")

        client = await self._ensure_client()
        if self.auto_create_bucket:
            await self.ensure_bucket(target_bucket)

        stream: BinaryIO
        if isinstance(data, (bytes, bytearray)):
            stream = io.BytesIO(data)
            computed_length = len(data)
        else:
            stream = data
            computed_length = length

        if computed_length is None:
            try:
                current_pos = stream.tell()
                stream.seek(0, io.SEEK_END)
                computed_length = stream.tell()
                stream.seek(current_pos, io.SEEK_SET)
            except (AttributeError, OSError):
                raise ValueError("Length must be provided for stream uploads") from None

        if computed_length <= 0:
            raise ValueError("Object length must be positive")

        result = await asyncio.to_thread(
            client.put_object,
            target_bucket,
            object_name,
            stream,
            computed_length,
            content_type=content_type,
            metadata=metadata,
        )
        return result.etag

    async def download_file(
        self,
        object_name: str,
        destination_path: Union[str, Path],
        bucket_name: Optional[str] = None,
    ) -> Path:
        target_bucket = bucket_name or self.bucket_name
        if not target_bucket:
            raise ValueError("Bucket name must be provided")

        client = await self._ensure_client()
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(client.fget_object, target_bucket, object_name, str(destination))
        return destination

    async def download_data(
        self,
        object_name: str,
        bucket_name: Optional[str] = None,
    ) -> bytes:
        """Download object content directly to memory.
        
        Args:
            object_name: Name of the object to download
            bucket_name: Optional bucket name, uses default if not provided
            
        Returns:
            Object content as bytes
            
        Raises:
            ValueError: If bucket name is not provided
            S3Error: If object doesn't exist or other MinIO errors
        """
        target_bucket = bucket_name or self.bucket_name
        if not target_bucket:
            raise ValueError("Bucket name must be provided")

        client = await self._ensure_client()
        
        def _download():
            response = client.get_object(target_bucket, object_name)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        
        return await asyncio.to_thread(_download)

    async def generate_presigned_url(
        self,
        object_name: str,
        method: str = "GET",
        expires: int = 3600,
        bucket_name: Optional[str] = None,
        request_params: Optional[Dict[str, str]] = None,
    ) -> str:
        target_bucket = bucket_name or self.bucket_name
        if not target_bucket:
            raise ValueError("Bucket name must be provided")

        client = await self._ensure_client()
        method_upper = method.upper()
        kwargs: Dict[str, object] = {"expires": timedelta(seconds=expires)}
        if request_params:
            if method_upper == "GET":
                kwargs["response_headers"] = request_params
            else:
                kwargs["extra_query_params"] = request_params

        return await asyncio.to_thread(
            client.get_presigned_url,
            method_upper,
            target_bucket,
            object_name,
            **kwargs,
        )

    async def remove_object(self, object_name: str, bucket_name: Optional[str] = None) -> None:
        target_bucket = bucket_name or self.bucket_name
        if not target_bucket:
            raise ValueError("Bucket name must be provided")

        client = await self._ensure_client()
        await asyncio.to_thread(client.remove_object, target_bucket, object_name)

    async def list_objects(
        self,
        bucket_name: Optional[str] = None,
        prefix: Optional[str] = None,
        recursive: bool = False,
    ) -> AsyncIterator[str]:
        target_bucket = bucket_name or self.bucket_name
        if not target_bucket:
            raise ValueError("Bucket name must be provided")

        client = await self._ensure_client()
        objects = await asyncio.to_thread(
            lambda: list(client.list_objects(target_bucket, prefix=prefix, recursive=recursive))
        )
        for obj in objects:
            yield obj.object_name
