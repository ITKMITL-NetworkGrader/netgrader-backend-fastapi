import asyncio
import logging
import re
from typing import Any
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
    if len(request.yaml_content.encode("utf-8")) > config.TEMPLATE_TEST_MAX_YAML_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"YAML template exceeds the {config.TEMPLATE_TEST_MAX_YAML_SIZE // 1024} KB size limit"
        )

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

            try:
                result = await asyncio.wait_for(
                    grading_service.process_grading_job(request.job_payload),
                    timeout=config.TEMPLATE_TEST_TIMEOUT,
                )
            except asyncio.TimeoutError:
                raise HTTPException(
                    status_code=504,
                    detail=f"Template test timed out after {config.TEMPLATE_TEST_TIMEOUT} seconds"
                )
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

class ParseDryRunRequest(BaseModel):
    input: str
    parser: str = "regex"
    pattern: str | None = None
    template: str | None = None
    platform: str | None = None
    command: str | None = None


class ParseDryRunResponse(BaseModel):
    success: bool
    result: Any | None = None
    error: str | None = None


@app.post("/template-tests/parse-dry-run", response_model=ParseDryRunResponse)
async def parse_dry_run(request: ParseDryRunRequest):
    """
    Execute a single parse_output action in isolation (no device connection).
    Used by the frontend Dry Run tab to test parse_output steps without a live device.
    Always returns HTTP 200; errors are surfaced via success=False + error field.
    """
    parser_type = (request.parser or "regex").lower()

    try:
        if parser_type == "regex":
            if not request.pattern:
                return ParseDryRunResponse(success=False, error="Regex parser requires 'pattern'")
            try:
                matches = re.findall(request.pattern, request.input, re.MULTILINE | re.IGNORECASE)
            except re.error as exc:
                return ParseDryRunResponse(success=False, error=f"Invalid regex pattern: {exc}")
            # Flatten single-group tuples to plain strings for cleaner output
            flat = [m[0] if isinstance(m, tuple) and len(m) == 1 else m for m in matches]
            return ParseDryRunResponse(success=True, result={
                "matches": flat,
                "match_count": len(flat),
                "first_match": flat[0] if flat else None,
            })

        if parser_type == "textfsm":
            # NTC-templates mode: platform + command provided (pre-built templates)
            if request.platform and request.command:
                try:
                    from ntc_templates.parse import parse_output as ntc_parse_output
                except ImportError:
                    return ParseDryRunResponse(success=False, error="ntc-templates is not available in this environment")
                try:
                    rows = ntc_parse_output(platform=request.platform, command=request.command, data=request.input or "")
                except Exception as exc:
                    return ParseDryRunResponse(success=False, error=f"NTC-templates parsing failed: {exc}")
                return ParseDryRunResponse(success=True, result=rows)
            # Inline TextFSM mode: raw template string provided
            try:
                import textfsm as _textfsm
                import io as _io
            except ImportError:
                return ParseDryRunResponse(success=False, error="TextFSM parser is not available in this environment")
            if not request.template:
                return ParseDryRunResponse(success=False, error="TextFSM parser requires either 'platform'+'command' (NTC-templates) or a 'template' string")
            try:
                fsm = _textfsm.TextFSM(_io.StringIO(request.template))
                rows = fsm.ParseText(request.input or "")
            except Exception as exc:
                return ParseDryRunResponse(success=False, error=f"TextFSM parsing failed: {exc}")
            structured = [dict(zip(fsm.header, r)) for r in rows]
            return ParseDryRunResponse(success=True, result=structured)

        if parser_type == "jinja":
            import json as _json
            import yaml as _yaml
            from jinja2 import TemplateError
            from jinja2.sandbox import SandboxedEnvironment
            tmpl_src = request.template or request.pattern or ""
            if not tmpl_src:
                return ParseDryRunResponse(success=False, error="Jinja parser requires a 'template' or 'pattern' parameter")
            env = SandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
            # Try to parse input as structured data (JSON) so templates can
            # iterate over objects directly. Falls back to raw string if not JSON.
            raw_input = request.input or ""
            try:
                input_value = _json.loads(raw_input)
            except Exception:
                input_value = raw_input
            try:
                rendered = env.from_string(tmpl_src).render(input=input_value)
            except TemplateError as exc:
                return ParseDryRunResponse(success=False, error=f"Jinja rendering failed: {exc}")
            # Attempt to auto-parse rendered output as JSON then YAML
            structured = rendered
            stripped = rendered.strip() if isinstance(rendered, str) else rendered
            if stripped:
                try:
                    structured = _json.loads(stripped)
                except Exception:
                    try:
                        structured = _yaml.safe_load(stripped)
                    except Exception:
                        pass
            return ParseDryRunResponse(success=True, result=structured)

        return ParseDryRunResponse(success=False, error=f"Unsupported parser type '{parser_type}'. Supported: regex, textfsm, jinja")

    except Exception as exc:
        logger.error(f"parse_dry_run failed unexpectedly: {exc}")
        return ParseDryRunResponse(success=False, error=str(exc))


class ValidateDryRunRequest(BaseModel):
    variables: dict
    rules: list[dict]   # [{field, condition, value, description?}]
    parameters: dict = {}  # Template parameters; Jinja in rule values is rendered with {**parameters, **variables}


class ValidateDryRunResponse(BaseModel):
    success: bool
    results: list[dict]
    all_passed: bool
    error: str | None = None


@app.post("/template-tests/validate-dry-run", response_model=ValidateDryRunResponse)
async def validate_dry_run(request: ValidateDryRunRequest):
    """
    Evaluate validation rules against a user-supplied variables dict.
    Used by the frontend Dry Run tab — no device connection required.
    Always returns HTTP 200; errors are surfaced via success=False + error field.
    """
    try:
        from app.services.custom_tasks.custom_task_executor import CustomTaskValidationEngine
        from app.services.custom_tasks.custom_task_registry import (
            CustomTaskValidationRule, CustomTaskValidationCondition
        )
        from jinja2.sandbox import SandboxedEnvironment
        from jinja2 import TemplateError as JinjaTemplateError

        # Build Jinja context: parameters take lower precedence than variables so
        # live register values always win over template defaults.
        jinja_ctx = {**request.parameters, **request.variables}
        jinja_env = SandboxedEnvironment()

        def _render(value: any) -> any:
            """Render Jinja expressions inside string values; non-strings pass through."""
            if not isinstance(value, str):
                return value
            try:
                return jinja_env.from_string(value).render(**jinja_ctx)
            except JinjaTemplateError:
                return value  # return raw string if template is invalid

        results = []
        for rule_dict in request.rules:
            rendered_field       = _render(rule_dict.get("field", ""))
            rendered_value       = _render(rule_dict.get("value"))
            rendered_description = _render(rule_dict.get("description"))
            try:
                condition = CustomTaskValidationCondition(rule_dict.get("condition", "equals"))
            except ValueError:
                results.append({
                    "field":       rendered_field,
                    "condition":   rule_dict.get("condition", "?"),
                    "expected":    rendered_value,
                    "actual":      None,
                    "passed":      False,
                    "description": rendered_description,
                    "error":       f"Unknown condition: {rule_dict.get('condition')}",
                })
                continue
            rule = CustomTaskValidationRule(
                field=rendered_field,
                condition=condition,
                value=rendered_value,
                description=rendered_description,
            )
            results.append(CustomTaskValidationEngine.validate_result(request.variables, rule))
        return ValidateDryRunResponse(
            success=True,
            results=results,
            all_passed=all(r.get("passed", False) for r in results),
        )
    except Exception as exc:
        logger.error(f"validate_dry_run failed unexpectedly: {exc}")
        return ValidateDryRunResponse(success=False, results=[], all_passed=False, error=str(exc))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=config.LOG_LEVEL.lower()
    )