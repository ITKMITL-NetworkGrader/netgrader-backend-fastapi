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

class TestCase(BaseModel):
    """Individual test case with expected vs actual comparison"""
    description: str = Field(..., description="What this test case validates")
    expected_value: Any = Field(..., description="Expected value for comparison")
    comparison_type: str = Field(default="equals", description="Type of comparison: equals, contains, regex, range, exists")
    points: int = Field(default=1, description="Points for this specific test case")
    required: bool = Field(default=True, description="Whether this test case is required to pass")

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
    test_cases: List[TestCase] = Field(
        default_factory=list,
        description="List of test cases with expected values for detailed scoring"
    )
    points: int = Field(default=1, description="Total points awarded for passing this test")
    
    # Backward compatibility
    expected_result: Optional[str] = Field(
        default=None,
        description="Legacy expected result field (deprecated, use test_cases instead)",
    )

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

class GradingResult(BaseModel):
    job_id: str
    status: str  # "running", "completed", "failed"
    total_points_earned: int
    total_points_possible: int
    test_results: List[TestResult]
    total_execution_time: float
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
