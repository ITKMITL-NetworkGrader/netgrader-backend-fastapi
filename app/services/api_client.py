import httpx
import asyncio
import logging
from typing import Optional
from app.schemas.models import ProgressUpdate, GradingResult
from app.core.config import config

logger = logging.getLogger(__name__)

class APIClient:
    """Client for sending progress updates and results back to the ElysiaJS server"""
    
    def __init__(self):
        self.timeout = config.CALLBACK_TIMEOUT
        self.max_retries = config.MAX_RETRIES
    
    async def send_progress_update(self, callback_url: str, progress: ProgressUpdate) -> bool:
        """Send real-time progress update to the ElysiaJS server"""
        if not callback_url:
            logger.warning("No callback URL provided for progress update")
            return False
            
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                print(f"{callback_url}/progress")
                response = await client.post(
                    f"{callback_url}/progress",
                    json=progress.model_dump(),
                    headers={"Content-Type": "application/json"}
                )
                # response.raise_for_status()
                logger.info(f"Progress update sent for job {progress.job_id}: {progress.message}")
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
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    print(f"{callback_url}/result")
                    print(result.model_dump())
                    response = await client.post(
                        f"{callback_url}/result",
                        json=result.model_dump(),
                        headers={"Content-Type": "application/json"}
                    )
                    # response.raise_for_status()
                    logger.info(f"Final result sent for job {result.job_id}")
                    return True
            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed to send final result for job {result.job_id}: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
        
        logger.error(f"Failed to send final result for job {result.job_id} after {self.max_retries} attempts")
        return False
    
    async def notify_job_started(self, callback_url: str, job_id: str) -> bool:
        """Notify that a grading job has started"""
        if not callback_url:
            return False
            
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                print(f"{callback_url}/started")
                response = await client.post(
                    f"{callback_url}/started",
                    json={"job_id": job_id, "status": "started"},
                    headers={"Content-Type": "application/json"}
                )
                # response.raise_for_status()
                logger.info(f"Job started notification sent for job {job_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to send job started notification for job {job_id}: {e}")
            return False