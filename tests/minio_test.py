import asyncio
from app.services.connectivity.minio_service import MinioService
from app.core.config import config

minio = MinioService()

async def main():
    async for obj in minio.list_objects(config.MINIO_BUCKET_NAME, recursive=True):
        print(obj)

asyncio.run(main())