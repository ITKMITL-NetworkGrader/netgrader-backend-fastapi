from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from enum import Enum

class ExecutionMode(str, Enum):
    ISOLATED = "isolated"     # Fresh connection for each task (default)
    STATEFUL = "stateful"     # Persistent connection across tasks in sequence
    SHARED = "shared"         # Shared connection pool for device

class ConnectionType(str, Enum):
    NETWORK_CLI = "network_cli"
    SSH = "ssh"
    LOCAL = "local"

class Device(BaseModel):
    id: str
    ip_address: str
    connection_type: str
    credentials: Dict[str, str] = Field(default_factory=dict)
    platform: Optional[str] = None
    jump_host: Optional[str] = Field(None, description="Jump host device ID for proxy connections")
    ssh_args: Optional[str] = Field(None, description="Custom SSH arguments for connection")
    use_persistent_connection: Optional[bool] = Field(False, description="Use persistent connection through jump host")
    role: Optional[str] = Field("direct", description="Device role: 'proxy_host', 'proxy_target', 'direct'")
    proxy_host: Optional[str] = Field(None, description="Proxy host device ID for two-stage SSH")
    proxy_credentials: Optional[Dict[str, str]] = Field(None, description="Credentials for proxy target device")

class TestCase(BaseModel):
    """Individual test case with expected vs actual comparison"""
    comparison_type: str = Field(..., description="Type of comparison: equals, contains, regex, success, ssh_success, greater_than, ipv6_equals, ipv6_link_local, ipv6_valid")
    expected_result: Any = Field(..., description="Expected value/result for comparison")

class NetworkTask(BaseModel):
    task_id: str
    name: Optional[str] = None
    template_name: str
    execution_device: str = Field(..., description="Primary device where task executes")
    target_device: Optional[str] = Field(None, description="Optional target device for multi-device tasks")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    test_cases: List[TestCase] = Field(default_factory=list)
    points: int = Field(default=1)
    group_id: Optional[str] = Field(None, description="Optional group ID for task grouping")
    execution_mode: ExecutionMode = Field(ExecutionMode.ISOLATED, description="Connection execution mode")
    stateful_session_id: Optional[str] = Field(None, description="Session ID for stateful connections")
    connection_timeout: Optional[int] = Field(30, description="Connection timeout in seconds")

class TaskGroup(BaseModel):
    """Task group configuration for all-or-nothing or proportional scoring"""
    group_id: str
    title: str
    description: Optional[str] = None
    group_type: str = Field("all_or_nothing", description="'all_or_nothing' or 'proportional'")
    points: int = Field(..., description="Total points for the entire group")
    rescue_tasks: List[NetworkTask] = Field(default_factory=list, description="Tasks to run when group fails")
    cleanup_tasks: List[NetworkTask] = Field(default_factory=list, description="Tasks to always run after group")
    continue_on_failure: bool = Field(True, description="Whether to continue execution if group fails")
    timeout_seconds: Optional[int] = Field(None, description="Group execution timeout in seconds")

class Part(BaseModel):
    part_id: str
    title: str
    network_tasks: List[NetworkTask]
    groups: List[TaskGroup] = Field(default_factory=list, description="Task group configurations")

class GradingJob(BaseModel):
    job_id: str
    student_id: str
    lab_id: str
    part: Part
    devices: List[Device]
    ip_mappings: Dict[str, str] = Field(default_factory=dict)
    callback_url: Optional[str] = Field(None, description="Per-job callback URL override for playground jobs")


class TestCaseResult(BaseModel):
    """Result of individual test case"""
    description: str
    expected_value: Any
    actual_value: Any
    comparison_type: str
    status: str  # "passed", "failed", "error"
    points_earned: int
    points_possible: int
    message: str

class DebugInfo(BaseModel):
    """Debug information for custom task execution"""
    enabled: bool = False
    parameters_received: Optional[Dict[str, Any]] = None
    registered_variables: Optional[Dict[str, Any]] = None
    command_results: Optional[List[Dict[str, Any]]] = None
    validation_details: Optional[List[Dict[str, Any]]] = None
    custom_debug_points: Optional[Dict[str, Any]] = None


class TestResult(BaseModel):
    test_name: str
    status: str  # "passed", "failed", "error"
    message: str
    points_earned: int
    points_possible: int
    execution_time: float
    test_case_results: List[TestCaseResult] = Field(default_factory=list)
    extracted_data: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Raw data extracted from device")
    raw_output: Optional[str] = ""
    debug_info: Optional[DebugInfo] = None
    group_id: Optional[str] = Field(None, description="Group ID if task belongs to a group")

class GroupResult(BaseModel):
    """Result of task group evaluation"""
    group_id: str
    title: str
    status: str  # "passed", "failed", "cancelled"
    group_type: str
    points_earned: int
    points_possible: int
    execution_time: float
    task_results: List[TestResult]
    message: str
    rescue_executed: bool = Field(False, description="Whether rescue tasks were executed")
    cleanup_executed: bool = Field(False, description="Whether cleanup tasks were executed")  

class GradingResult(BaseModel):
    job_id: str
    status: str  # "running", "completed", "failed", "cancelled"
    total_points_earned: int
    total_points_possible: int
    test_results: List[TestResult]
    group_results: List[GroupResult] = Field(default_factory=list, description="Results for task groups")
    total_execution_time: float
    error_message: Optional[str] = ""
    created_at: str
    completed_at: Optional[str] = ""
    cancelled_reason: Optional[str] = Field(None, description="Reason for early cancellation")

class ProgressUpdate(BaseModel):
    job_id: str
    status: str
    message: str
    current_test: Optional[str] = ""
    tests_completed: int
    total_tests: int
    percentage: float
