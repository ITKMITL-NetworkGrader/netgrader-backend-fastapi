import asyncio
import logging
import sentry_sdk
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.schemas.models import GradingJob
from app.services.pipeline.queue_consumer import consumer, start_consumer, stop_consumer
from app.core.config import config

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

if config.SENTRY_DSN:
    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        send_default_pii=config.SENTRY_SEND_DEFAULT_PII,
        enable_logs=config.SENTRY_ENABLE_LOGS,
        traces_sample_rate=config.SENTRY_TRACES_SAMPLE_RATE,
        profile_session_sample_rate=config.SENTRY_PROFILE_SESSION_SAMPLE_RATE,
        profile_lifecycle=config.SENTRY_PROFILE_LIFECYCLE,
        environment=config.SENTRY_ENVIRONMENT,
    )
    logger.info("Sentry initialized")
else:
    logger.info("Sentry not configured (SENTRY_DSN is empty)")

# Background task to run the queue consumer
consumer_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan - start/stop background services"""
    global consumer_task
    
    # Startup
    logger.info("Starting NetGrader FastAPI Worker")
    
    # Start queue consumer
    consumer_task = asyncio.create_task(start_consumer())
    
    yield
    
    # Shutdown
    logger.info("Shutting down NetGrader FastAPI Worker")
    if consumer_task:
        consumer_task.cancel()
    await stop_consumer()

app = FastAPI(
    title="NetGrader Worker API",
    description="""
    FastAPI worker service for automated network lab grading
    
    Core Features:
    1. Job Consumption - Constantly listening to RabbitMQ queue
    2. Dynamic Task Execution - Nornir framework executes network tasks
    3. Multi-Protocol Support - SSH, SNMP, and network CLI connections
    4. Real-Time Feedback - Streams progress updates via API callbacks
    """,
    version="1.0.0",
    lifespan=lifespan
)

# NG-SEC-011: Restrict CORS origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS.split(","),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    """Health check endpoint"""
    return {"status": "ok"}

@app.get("/health")
def health_check():
    """Detailed health check"""
    return {
        "status": "healthy",
        "services": {
            "queue_consumer": "running" if consumer.is_running else "stopped"
        }
    }

@app.post("/jobs/queue")
async def queue_grading_job(job: GradingJob):
    """Add a grading job to the RabbitMQ queue"""
    try:
        await consumer.publish_job(job)
        return {
            "message": f"Grading job {job.job_id} queued successfully",
            "job_id": job.job_id,
            "status": "queued"
        }
    except Exception as e:
        logger.error(f"Failed to queue grading job: {e}")
        raise HTTPException(status_code=500, detail="Failed to queue grading job")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=config.LOG_LEVEL.lower()
    )