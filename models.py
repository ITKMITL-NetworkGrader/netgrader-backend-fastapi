from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from enum import Enum

class ConnectionType(str, Enum):
    NETWORK_CLI = "ansible.netcommon.network_cli"
    SSH = "ssh"
    LOCAL = "local"

class Device(BaseModel):
    hostname: str
    ip_address: str
    connection_type: ConnectionType
    platform: Optional[str] = None  # e.g., "cisco_ios", "linux"
    username: Optional[str] = None
    password: Optional[str] = None
    ssh_key_path: Optional[str] = None

class TestDefinition(BaseModel):
    test_id: str
    test_type: str  # e.g., "network_ping", "linux_ip_check", "custom"
    template_name: str  # corresponds to Jinja2 template file
    parameters: Dict[str, Any] = Field(default_factory=dict)
    source_device: Optional[str] = None
    target_device: Optional[str] = None
    expected_result: Optional[str] = None
    points: int = 1

class LabTopology(BaseModel):
    devices: List[Device]
    tests: List[TestDefinition]

class GradingJob(BaseModel):
    job_id: str
    instructor_id: str
    lab_name: str
    student_id: str
    topology: LabTopology
    callback_url: Optional[str] = None  # URL to send progress updates
    total_points: int = Field(default=0)

class TestResult(BaseModel):
    test_id: str
    status: str  # "passed", "failed", "error"
    message: str
    points_earned: int
    points_possible: int
    execution_time: float
    raw_output: Optional[str] = None

class GradingResult(BaseModel):
    job_id: str
    status: str  # "running", "completed", "failed"
    total_points_earned: int
    total_points_possible: int
    test_results: List[TestResult]
    execution_time: float
    error_message: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None

class ProgressUpdate(BaseModel):
    job_id: str
    status: str
    message: str
    current_test: Optional[str] = None
    tests_completed: int
    total_tests: int
    percentage: float
