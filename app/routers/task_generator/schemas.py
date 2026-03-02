"""
Pydantic schemas for Task Generator Script Management API
"""
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


# =============================================================================
# Enums
# =============================================================================

class DeviceType(str, Enum):
    HOST = "host"
    NETWORK_DEVICE = "network_device"


class OSType(str, Enum):
    LINUX = "linux"
    CISCO = "cisco"


# =============================================================================
# Request Models
# =============================================================================

class SubTaskCheck(BaseModel):
    """Single sub-task to check for script availability"""
    id: int = Field(..., description="Sub-task ID")
    action: str = Field(..., description="Action name e.g. ping, show_interface")
    device_type: DeviceType = Field(..., description="Device type: host or network_device")
    os: OSType = Field(..., description="OS type: linux or cisco")
    source_device: Optional[str] = Field(None, description="Source device name")
    target_device: Optional[str] = Field(None, description="Target device name")
    params: Optional[dict] = Field(default_factory=dict, description="Additional parameters")
    description: Optional[str] = Field(None, description="Task description")


class ScriptCheckRequest(BaseModel):
    """Request to check which sub-tasks have scripts available"""
    tasks: list[SubTaskCheck] = Field(..., description="List of sub-tasks to check")


class ScriptSaveRequest(BaseModel):
    """Request to save a new script"""
    device_type: DeviceType = Field(..., description="Device type")
    os: OSType = Field(..., description="OS type")
    action: str = Field(..., description="Action name (will be used as filename)")
    code: str = Field(..., description="Python script code content")
    description: Optional[str] = Field(None, description="Script description")


class ScriptExecuteTask(BaseModel):
    """Single task to execute"""
    id: int = Field(..., description="Task ID")
    action: str = Field(..., description="Action name")
    device_type: DeviceType = Field(..., description="Device type")
    os: OSType = Field(..., description="OS type")
    source_device: Optional[str] = Field(None, description="Source device name")
    target_device: Optional[str] = Field(None, description="Target device name")
    params: Optional[dict] = Field(default_factory=dict, description="Parameters for the script")


class ScriptExecuteRequest(BaseModel):
    """Request to execute scripts for a list of tasks"""
    tasks: list[ScriptExecuteTask] = Field(..., description="List of tasks to execute")


# =============================================================================
# Response Models
# =============================================================================

class ScriptStatus(BaseModel):
    """Status of a single sub-task script"""
    id: int
    action: str
    device_type: str
    os: str
    found: bool
    script_path: Optional[str] = None


class ScriptCheckResponse(BaseModel):
    """Response from script check endpoint"""
    total: int
    found_count: int
    missing_count: int
    tasks: list[ScriptStatus]


class ScriptSaveResponse(BaseModel):
    """Response from script save endpoint"""
    success: bool
    message: str
    script_path: Optional[str] = None


class TaskExecutionResult(BaseModel):
    """Result of executing a single task"""
    id: int
    action: str
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None


class ScriptExecuteResponse(BaseModel):
    """Response from script execute endpoint"""
    total: int
    success_count: int
    failure_count: int
    results: list[TaskExecutionResult]
