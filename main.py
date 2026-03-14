import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from app.schemas.models import GradingJob
from app.services.grading.simple_grading_service import SimpleGradingService
from app.services.custom_tasks.custom_task_registry import CustomTaskValidationError, CustomTaskDefinition
from app.services.pipeline.queue_consumer import consumer, start_consumer, stop_consumer
from app.core.config import config

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Background task to run the queue consumer
consumer_task = None
template_test_lock = asyncio.Lock()


class TemplateTestRunRequest(BaseModel):
    yaml_content: str = Field(..., min_length=1)
    job_payload: GradingJob
    validate_only: bool = False
    task_name_override: str | None = None


class TemplateTestRunResponse(BaseModel):
    success: bool
    mode: str
    template_name: str
    validation: dict
    grading_result: dict | None = None

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


@app.post("/template-tests/run", response_model=TemplateTestRunResponse)
async def run_template_test(request: TemplateTestRunRequest):
    """
    Run direct template validation/execution without RabbitMQ queueing.

    This endpoint is designed for live template authoring workflows.
    """
    grading_service = SimpleGradingService()
    await grading_service.initialize()

    task_definition: CustomTaskDefinition | None = None
    previous_definition: CustomTaskDefinition | None = None

    async with template_test_lock:
        try:
            task_definition = grading_service.global_task_registry.register_temporary_template_from_yaml(
                yaml_content=request.yaml_content,
                task_name_override=request.task_name_override,
                register=False,
            )
            previous_definition = grading_service.global_task_registry.get_template(task_definition.task_name)
            grading_service.global_task_registry.upsert_template(task_definition)
        except CustomTaskValidationError as exc:
            raise HTTPException(status_code=400, detail=f"Template validation failed: {exc}")
        except Exception as exc:
            logger.error(f"Failed to register temporary template: {exc}")
            raise HTTPException(status_code=500, detail="Failed to prepare template test run")

        try:
            validation = await grading_service.validate_job_payload(request.job_payload)
            if not validation.get("valid", False):
                return TemplateTestRunResponse(
                    success=False,
                    mode="validate_only" if request.validate_only else "execute",
                    template_name=task_definition.task_name,
                    validation=validation,
                    grading_result=None,
                )

            if request.validate_only:
                return TemplateTestRunResponse(
                    success=True,
                    mode="validate_only",
                    template_name=task_definition.task_name,
                    validation=validation,
                    grading_result=None,
                )

            result = await grading_service.process_grading_job(request.job_payload)
            return TemplateTestRunResponse(
                success=result.status == "completed",
                mode="execute",
                template_name=task_definition.task_name,
                validation=validation,
                grading_result=result.model_dump(),
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"Template test run failed: {exc}")
            raise HTTPException(status_code=500, detail=f"Template test run failed: {exc}")
        finally:
            # Restore the previous template mapping to avoid polluting global runtime state.
            if task_definition:
                if previous_definition:
                    grading_service.global_task_registry.upsert_template(previous_definition)
                else:
                    grading_service.global_task_registry.remove_template(task_definition.task_name)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=config.LOG_LEVEL.lower()
    )