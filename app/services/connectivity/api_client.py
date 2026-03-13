import os
import httpx
import asyncio
import logging
from typing import Optional, List, Any, Dict

from pydantic import BaseModel

from app.schemas.models import ProgressUpdate, GradingResult
from app.core.config import config

WORKER_CALLBACK_SECRET = config.WORKER_CALLBACK_SECRET

logger = logging.getLogger(__name__)

class APIClient:
    """Client for sending progress updates and results back to the ElysiaJS server"""
    
    def __init__(self):
        self.timeout = config.CALLBACK_TIMEOUT
        self.max_retries = config.MAX_RETRIES
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the shared HTTP client with connection pooling."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
                headers={"X-Worker-Secret": WORKER_CALLBACK_SECRET}
            )
        return self._client
    
    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    async def send_progress_update(self, callback_url: str, progress: ProgressUpdate) -> bool:
        """Send real-time progress update to the ElysiaJS server"""
        if not callback_url:
            logger.warning("No callback URL provided for progress update")
            return False
            
        try:
            client = await self._get_client()
            response = await client.post(
                f"{callback_url}/progress",
                json=progress.model_dump(),
                headers={"Content-Type": "application/json"}
            )
            logger.debug(f"Progress update sent for job {progress.job_id}: {progress.message}")
            return True
        except Exception as e:
            logger.error(f"Failed to send progress update for job {progress.job_id}: {e}")
            return False
    
    async def send_final_result(self, callback_url: str, result: GradingResult) -> bool:
        """Send final grading result to the ElysiaJS server"""
        if not callback_url:
            logger.warning("No callback URL provided for final result")
            return False

        for attempt in range(self.max_retries):
            try:
                client = await self._get_client()
                response = await client.post(
                    f"{callback_url}/result",
                    json=result.model_dump(),
                    headers={"Content-Type": "application/json"}
                )
                logger.info(f"Final result sent for job {result.job_id}")
                return True
            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed to send final result for job {result.job_id}: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
        
        logger.error(f"Failed to send final result for job {result.job_id} after {self.max_retries} attempts")
        return False

    def batfish(self) -> "BatfishAPI":
        """Return a Batfish API helper instance configured from global config."""
        return BatfishAPI(timeout=self.timeout, max_retries=self.max_retries)
    
    async def notify_job_started(self, callback_url: str, job_id: str) -> bool:
        """Notify that a grading job has started"""
        if not callback_url:
            return False
            
        try:
            client = await self._get_client()
            response = await client.post(
                f"{callback_url}/started",
                json={"job_id": job_id, "status": "started"},
                headers={"Content-Type": "application/json"}
            )
            logger.info(f"Job started notification sent for job {job_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to send job started notification for job {job_id}: {e}")
            return False
    
def _build_batfish_url(path: str) -> str:
    return f"{config.BATFISH_API.rstrip('/')}/{path.lstrip('/')}"


class BatfishAPI:
    """Helper wrapper around Batfish endpoints used by NetGrader."""

    def __init__(self, timeout: int = config.CALLBACK_TIMEOUT, max_retries: int = config.MAX_RETRIES):
        self.timeout = timeout
        self.max_retries = max_retries

    async def post_acl_lines_minio(self, request_json: Dict[str, Any]) -> Dict[str, Any]:
        """Post a request to /aclLines/minio using the exact JSON structure you provided.

        Expected shape:
        {
          "payload": { ... },          # BatfishModel-like
          "minio_payload": { ... }     # BatfishMinIOSnapshot-like
        }

        This method will forward the JSON as-is to the Batfish service and return parsed JSON.
        """
        url = _build_batfish_url("/question/aclLines/minio")

        # Basic validation to help catch mistakes early
        if not isinstance(request_json, dict):
            raise ValueError("request_json must be a dictionary")

        if "minio_payload" not in request_json:
            raise ValueError("request_json must contain 'minio_payload' key")

        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    logger.debug("Posting raw request to Batfish %s (attempt %d)", url, attempt + 1)
                    resp = await client.post(url, json=request_json)
                    resp.raise_for_status()
                    return resp.json()
            except Exception as exc:
                logger.error("Batfish raw POST attempt %d failed: %s", attempt + 1, exc)
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

        raise RuntimeError(f"Failed to POST to Batfish at {url} after {self.max_retries} attempts")
