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
    name: str = Field(..., description="A human-readable name for the test.")
    template: str = Field(
        ...,
        description="The filename of the Jinja2 task template, e.g., 'ping.yml.j2'.",
    )
    target_device: Optional[List[str]] = Field(
        ...,
        description="A list of inventory hostnames this test should run against.",
    )
    vars: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Variables to be passed to the Ansible task template.",
    )
    expected_result: Optional[str] = Field(
        default=None,
        description="Expected result of the test (e.g., 'success', 'failure').",
    )
    points: int = Field(default=1, description="Points awarded for passing this test")

class LabTopology(BaseModel):
    devices: List[Device]
    tests: List[TestDefinition]

class GradingJob(BaseModel):
    job_id: str
    instructor_id: str
    lab_name: str
    student_id: str
    topology: LabTopology
    callback_url: Optional[str] = ""  # URL to send progress updates
    total_points: int = Field(default=0)

class TestResult(BaseModel):
    test_name: str
    status: str  # "passed", "failed", "error"
    message: str
    points_earned: int
    points_possible: int
    execution_time: float
    raw_output: Optional[str] = ""  

class GradingResult(BaseModel):
    job_id: str
    status: str  # "running", "completed", "failed"
    total_points_earned: int
    total_points_possible: int
    test_results: List[TestResult]
    execution_time: float
    error_message: Optional[str] = ""
    created_at: str
    completed_at: Optional[str] = ""

class ProgressUpdate(BaseModel):
    job_id: str
    status: str
    message: str
    current_test: Optional[str] = ""
    tests_completed: int
    total_tests: int
    percentage: float
