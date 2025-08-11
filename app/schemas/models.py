from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from enum import Enum

class ConnectionType(str, Enum):
    NETWORK_CLI = "ansible.netcommon.network_cli"
    SSH = "ssh"
    LOCAL = "local"

class Device(BaseModel):
    id: str
    ip_address: str
    ansible_connection: str
    credentials: Dict[str, str] = Field(default_factory=dict)
    platform: Optional[str] = None

class TestCase(BaseModel):
    """Individual test case with expected vs actual comparison"""
    comparison_type: str = Field(..., description="Type of comparison: equals, contains, regex, success, ssh_success, greater_than")
    expected_result: Any = Field(..., description="Expected value/result for comparison")

class AnsibleTask(BaseModel):
    task_id: str
    template_name: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    test_cases: List[TestCase] = Field(default_factory=list)
    points: int = Field(default=1)

class Play(BaseModel):
    play_id: str
    source_device: str
    target_device: str
    ansible_tasks: List[AnsibleTask]

class Part(BaseModel):
    part_id: str
    title: str
    plays: List[Play]

class GradingJob(BaseModel):
    job_id: str
    student_id: str
    lab_id: str
    part: Part
    devices: List[Device]
    ip_mappings: Dict[str, str] = Field(default_factory=dict)
    callback_url: str

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
