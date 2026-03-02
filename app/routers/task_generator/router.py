"""
Task Generator Router - Script Management API

Endpoints:
- POST /task-generator/scripts/check   - Check script availability
- POST /task-generator/scripts/save    - Save a new script
- POST /task-generator/scripts/execute - Execute scripts on devices
"""
import logging
from fastapi import APIRouter, HTTPException

from .schemas import (
    ScriptCheckRequest, ScriptCheckResponse, ScriptStatus,
    ScriptSaveRequest, ScriptSaveResponse,
    ScriptExecuteRequest, ScriptExecuteResponse, TaskExecutionResult,
)
from . import script_manager

logger = logging.getLogger(__name__)

# =============================================================================
# Router
# =============================================================================

router = APIRouter(
    prefix="/task-generator",
    tags=["Task Generator"],
    responses={404: {"description": "Not found"}}
)


# =============================================================================
# POST /task-generator/scripts/check
# =============================================================================

@router.post(
    "/scripts/check",
    response_model=ScriptCheckResponse,
    summary="Check script availability",
    description="Check which sub-tasks have matching scripts in the storage"
)
async def check_scripts(request: ScriptCheckRequest):
    """Check if scripts exist for the given list of sub-tasks."""
    tasks_data = [
        {
            "id": t.id,
            "action": t.action,
            "device_type": t.device_type.value,
            "os": t.os.value
        }
        for t in request.tasks
    ]

    results = script_manager.check_scripts(tasks_data)

    found_count = sum(1 for r in results if r["found"])

    return ScriptCheckResponse(
        total=len(results),
        found_count=found_count,
        missing_count=len(results) - found_count,
        tasks=[
            ScriptStatus(
                id=r["id"],
                action=r["action"],
                device_type=r["device_type"],
                os=r["os"],
                found=r["found"],
                script_path=r["script_path"]
            )
            for r in results
        ]
    )


# =============================================================================
# POST /task-generator/scripts/save
# =============================================================================

@router.post(
    "/scripts/save",
    response_model=ScriptSaveResponse,
    summary="Save a new script",
    description="Save a Python script to the script storage"
)
async def save_script(request: ScriptSaveRequest):
    """Save a new script to script-storage/{device_type}/{os}/{action}.py"""
    result = script_manager.save_script(
        device_type=request.device_type.value,
        os_type=request.os.value,
        action=request.action,
        code=request.code,
        description=request.description
    )

    return ScriptSaveResponse(
        success=result["success"],
        message=result["message"],
        script_path=result["script_path"]
    )


# =============================================================================
# POST /task-generator/scripts/execute
# =============================================================================

@router.post(
    "/scripts/execute",
    response_model=ScriptExecuteResponse,
    summary="Execute scripts",
    description="Execute scripts for a list of tasks"
)
async def execute_scripts(request: ScriptExecuteRequest):
    """Execute scripts for each task in the list."""
    results = []

    for task in request.tasks:
        exec_result = script_manager.execute_script(
            device_type=task.device_type.value,
            os_type=task.os.value,
            action=task.action,
            params=task.params
        )

        results.append(TaskExecutionResult(
            id=task.id,
            action=task.action,
            success=exec_result["success"],
            output=exec_result["output"],
            error=exec_result["error"]
        ))

    success_count = sum(1 for r in results if r.success)

    return ScriptExecuteResponse(
        total=len(results),
        success_count=success_count,
        failure_count=len(results) - success_count,
        results=results
    )
