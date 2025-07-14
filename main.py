import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.schemas.models import GradingJob
from app.services.queue_consumer import consumer, start_consumer, stop_consumer
from app.core.config import config

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
    2. Dynamic Playbook Generation - Jinja2 templates create Ansible playbooks in-memory
    3. Execution - ansible-runner executes playbooks against lab environments
    4. Real-Time Feedback - Streams progress updates via API callbacks
    """,
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    """Health check endpoint"""
    return {
        "message": "NetGrader Worker API", 
        "status": "running",
        "version": "1.0.0",
        "core_features": [
            "Job Consumption (RabbitMQ)",
            "Dynamic Playbook Generation (Jinja2)",
            "Execution (ansible-runner)",
            "Real-Time Feedback (API callbacks)"
        ]
    }

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
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=config.LOG_LEVEL.lower()
    )