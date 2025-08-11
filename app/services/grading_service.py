import json
import yaml
import tempfile
import os
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path
import ansible_runner
from jinja2 import Environment, FileSystemLoader, Template
from app.schemas.models import (
    GradingJob, TestResult, GradingResult, ProgressUpdate, 
    Device, TestDefinition, ConnectionType, TestCase, TestCaseResult
)
from app.core.config import config
# from app.services.api_client import APIClient
from app.services.api_client_request import ApiClient
from app.services.scoring_service import ScoringService
from app.services.data_parser import DataParser

logger = logging.getLogger(__name__)

class GradingService:
    """Core service that generates Ansible playbooks and executes grading jobs"""
    
    def __init__(self):
        self.api_client = ApiClient()
        self.scoring_service = ScoringService()
        self.data_parser = DataParser()
        self.templates_dir = Path(config.TEMPLATES_DIR)
        self.jinja_env = Environment(loader=FileSystemLoader(self.templates_dir))
        
        # Ensure directories exist
        os.makedirs(config.ANSIBLE_INVENTORY_DIR, exist_ok=True)
        os.makedirs(config.ANSIBLE_PLAYBOOK_DIR, exist_ok=True)
    
    async def process_grading_job(self, job: GradingJob) -> GradingResult:
        """Main method to process a grading job"""
        start_time = datetime.now()
        logger.info(f"Starting grading job {job.job_id} for student {job.student_id}")
        
        # Initialize result
        result = GradingResult(
            job_id=job.job_id,
            status="running",
            total_points_earned=0,
            total_points_possible=sum(test.points for test in job.topology.tests),
            test_results=[],
            total_execution_time=0.0,
            created_at=start_time.isoformat()
        )
        
        try:
            # Notify job started
            if job.callback_url:
                self.api_client.callback(job.callback_url, "/started", {"job_id": job.job_id, "status": "started"})
            
            # Generate inventory file
            inventory_path = await self._generate_inventory(job)
            
            # Generate master playbook
            playbook_path = await self._generate_playbook(job)
            
            # Execute the playbook
            result = await self._execute_playbook(job, inventory_path, playbook_path, result)
            
            # Mark as completed
            result.status = "completed"
            result.completed_at = datetime.now().isoformat()
            
        except Exception as e:
            logger.error(f"Error processing job {job.job_id}: {e}")
            result.status = "failed"
            result.error_message = str(e)
            result.completed_at = datetime.now().isoformat()
        
        # Calculate final execution time
        end_time = datetime.now()
        result.total_execution_time = (end_time - start_time).total_seconds()
        # Send final result
        if job.callback_url:
            # print(result.model_dump())
            self.api_client.callback(job.callback_url, "/result", result.model_dump())
        
        logger.info(f"Completed grading job {job.job_id}. Score: {result.total_points_earned}/{result.total_points_possible}")
        return result
    
    async def _generate_inventory(self, job: GradingJob) -> str:
        """Generate Ansible inventory file for the lab topology"""
        inventory = {
            "all": {
                "children": {
                    "network_devices": {"hosts": {}},
                    "linux_servers": {"hosts": {}}
                }
            }
        }
        
        for device in job.topology.devices:
            host_config = {
                "ansible_host": device.ip_address,
                "ansible_connection": device.connection_type.value
            }
            if device.username:
                host_config["ansible_user"] = device.username
            if device.password:
                host_config["ansible_password"] = device.password
            if device.ssh_key_path:
                host_config["ansible_ssh_private_key_file"] = device.ssh_key_path
            if device.platform:
                host_config["ansible_network_os"] = device.platform
            
            # Add to appropriate group
            if device.connection_type == ConnectionType.NETWORK_CLI:
                inventory["all"]["children"]["network_devices"]["hosts"][device.hostname] = host_config
            else:
                inventory["all"]["children"]["linux_servers"]["hosts"][device.hostname] = host_config
        
        # Write inventory file
        inventory_path = os.path.join(config.ANSIBLE_INVENTORY_DIR, f"inventory_{job.job_id}.yml")
        with open(inventory_path, 'w') as f:
            yaml.dump(inventory, f, default_flow_style=False)
        
        logger.info(f"Generated inventory file: {inventory_path}")
        return inventory_path
    
    async def _generate_playbook(self, job: GradingJob) -> str:
        """Generate the master Ansible playbook with dynamic tasks using new template structure"""
        
        # Prepare tests data for the new template structure
        tests_data = []
        for test in job.topology.tests:
            # Merge test vars with expected_result if it exists
            template_vars = test.vars.copy()
            if test.expected_result:
                template_vars["expected_result"] = test.expected_result
            
            test_data = {
                "name": test.name,
                "template": test.template,
                "target_device": test.target_device,
                "vars": template_vars,
                "points": test.points
            }
            tests_data.append(test_data)
        
        # Load and render master playbook template
        master_template = self.jinja_env.get_template("master_playbook.j2")
        playbook_content = master_template.render(tests=tests_data)
        
        # Write playbook file
        playbook_path = os.path.join(config.ANSIBLE_PLAYBOOK_DIR, f"playbook_{job.job_id}.yml")
        with open(playbook_path, 'w') as f:
            f.write(playbook_content)
        
        logger.info(f"Generated playbook file: {playbook_path}")
        return playbook_path
    
    # Old template generation methods removed - now using include_tasks in master playbook
    
    async def _execute_playbook(self, job: GradingJob, inventory_path: str, playbook_path: str, result: GradingResult) -> GradingResult:
        """Execute the Ansible playbook and parse results"""
        try:# Send initial progress update
            if job.callback_url:
                progress = ProgressUpdate(
                    job_id=job.job_id,
                    status="executing",
                    message="Starting playbook execution",
                    tests_completed=0,
                    total_tests=len(job.topology.tests),
                    percentage=0.0
                )
                self.api_client.callback(job.callback_url, "/progress", progress.model_dump())
            private_data_dir = tempfile.mkdtemp(prefix=f"ansible_runner_{job.job_id}_")
        # Run ansible playbook
            runner_result = await asyncio.get_event_loop().run_in_executor(
                None,
                self._run_ansible_playbook,
                playbook_path,
                inventory_path,
                private_data_dir
            )
        
            # Parse results
            if runner_result.status == "successful":
                result = await self._parse_ansible_results(job, runner_result, result)
            else:
                result.status = "failed"
                result.error_message = f"Ansible execution failed: {runner_result.stdout}"
                logger.error(f"Ansible execution failed for job {job.job_id}: {runner_result.stderr}")
        
            return result
        finally:
            import shutil
            # Clean up temporary directory
            shutil.rmtree(private_data_dir, ignore_errors=True)

    
    def _run_ansible_playbook(self, playbook_path: str, inventory_path: str, private_data_dir: str) -> Any:
        """Run Ansible playbook synchronously"""
        
        result = ansible_runner.run(
                playbook=playbook_path,
                inventory=inventory_path,
                private_data_dir=private_data_dir,
                quiet=False,
                # verbosity=2
            )
        return result
    
    async def _parse_ansible_results(self, job: GradingJob, runner_result: Any, result: GradingResult) -> GradingResult:
        """Parse Ansible execution results and generate test results"""
        
        test_results = []
        tests_completed = 0
        
        # Create a mapping of test names to their definitions for easier lookup
        test_map = {test.name: test for test in job.topology.tests}
        
        for test in job.topology.tests:
            test_result = TestResult(
                test_name=test.name,
                status="error",
                message="Test not executed",
                points_earned=0,
                points_possible=test.points,
                execution_time=0.0
            )
            
            # Look for test results in ansible events
            # Check both task completion and evaluation events
            for event in runner_result.events:
                event_type = event.get('event')
                if event_type in ['runner_on_ok', 'runner_on_failed']:
                    task_name = event.get('event_data', {}).get('task', '')
                    # Match test by name or by test_id tag
                    if (test.name in task_name or 
                        f"test_id:{test.name}" in str(event.get('event_data', {}).get('res', {}).get('tags', []))):
                        
                        test_result = self._parse_test_event(test, event)
                        logger.info(f"Parsed result for test '{test.name}': {test_result.status} ({test_result.points_earned}/{test_result.points_possible} points)")
                        break
            
            test_results.append(test_result)
            tests_completed += 1
            
            # Send progress update
            if job.callback_url:
                progress = ProgressUpdate(
                    job_id=job.job_id,
                    status="executing",
                    message=f"Completed test: {test.name}",
                    current_test=test.name,
                    tests_completed=tests_completed,
                    total_tests=len(job.topology.tests),
                    percentage=(tests_completed / len(job.topology.tests)) * 100
                )
                self.api_client.callback(job.callback_url, "/progress", progress.model_dump())
        
        result.test_results = test_results
        result.total_points_earned = sum(tr.points_earned for tr in test_results)
        
        logger.info(f"Final grading results: {result.total_points_earned}/{result.total_points_possible} points across {len(test_results)} tests")
        return result
    
    def _parse_test_event(self, test: TestDefinition, event: Dict[str, Any]) -> TestResult:
        """Parse individual test result from Ansible event with advanced scoring"""
        event_data = event.get('event_data', {})
        task_result = event_data.get('res', {})
        
        # Extract data from ansible facts/variables
        extracted_data = self._extract_test_data(event, task_result)
        print(f"\nExtracted Data : {extracted_data}\n")
        # Use new scoring system if test cases are defined
        if test.test_cases:
            print("Analyze Testcase")
            test_case_results = self.scoring_service.evaluate_test_cases(test, extracted_data)
            points_earned, message = self.scoring_service.calculate_test_score(test_case_results, test.points)
            status = "passed" if points_earned > 0 else "failed"
            print(f"\nTestcase result : {json.dumps(test_case_results)}\nPoints Earned : {points_earned}\n")
            return TestResult(
                test_name=test.name,
                status=status,
                message=message,
                points_earned=points_earned,
                points_possible=test.points,
                execution_time=event_data.get('duration', 0.0),
                test_case_results=test_case_results,
                extracted_data=extracted_data,
                raw_output=json.dumps(task_result, indent=2)
            )
        
        # Fallback to legacy scoring for backward compatibility
        else:
            print("Legacy parse")
            return self._legacy_parse_test_event(test, event_data, task_result, extracted_data)
    
    def _extract_test_data(self, event: Dict[str, Any], task_result: Dict[str, Any]) -> Dict[str, Any]:
        """Extract and parse test data from Ansible task results"""
        extracted_data = {}
        
        # Method 1: Look for set_fact tasks with grading data (preferred)
        if 'ansible_facts' in task_result:
            facts = task_result['ansible_facts']
            
            # Check for new grading_data structure
            if 'grading_data' in facts:
                grading_data = facts['grading_data']
                logger.info(f"Found grading_data for test type: {grading_data.get('test_type', 'unknown')}")
                
                # Use DataParser to convert raw data to structured data
                try:
                    parsed_data = self.data_parser.parse_raw_data(grading_data)
                    extracted_data.update(parsed_data)
                    logger.info(f"Successfully parsed grading_data: {list(parsed_data.keys())}")
                except Exception as e:
                    logger.error(f"Failed to parse grading_data: {e}")
                    # Fallback to raw grading data
                    extracted_data.update(grading_data)
            
            # Legacy support: Look for *_data patterns
            else:
                for key, value in facts.items():
                    if key.endswith('_data'):  # ping_data, service_data, etc.
                        extracted_data.update(value if isinstance(value, dict) else {key: value})
        
        # Method 2: Look for debug output with raw data (alternative approach)
        if 'msg' in task_result and isinstance(task_result['msg'], dict):
            raw_data = task_result['msg']
            
            # Check if this is raw data that needs parsing
            if 'test_type' in raw_data and 'raw_result' in raw_data:
                logger.info(f"Found debug raw data for test type: {raw_data['test_type']}")
                
                # Use DataParser to convert raw data to structured data
                try:
                    parsed_data = self.data_parser.parse_raw_data(raw_data)
                    extracted_data.update(parsed_data)
                    logger.info(f"Successfully parsed debug data: {list(parsed_data.keys())}")
                except Exception as e:
                    logger.error(f"Failed to parse debug raw data: {e}")
                    # Fallback to raw data
                    extracted_data.update(raw_data)
            else:
                # Regular debug output
                extracted_data.update(raw_data)
        
        # Method 3: Extract basic command results (fallback)
        stdout = task_result.get('stdout', '')
        stderr = task_result.get('stderr', '')
        
        if stdout:
            extracted_data['stdout'] = stdout
        if stderr:
            extracted_data['stderr'] = stderr
            
        # Extract return code
        if 'rc' in task_result:
            extracted_data['return_code'] = task_result['rc']
            
        logger.debug(f"Final extracted data keys: {list(extracted_data.keys())}")
        return extracted_data
    
    def _legacy_parse_test_event(self, test: TestDefinition, event_data: Dict[str, Any], 
                                task_result: Dict[str, Any], extracted_data: Dict[str, Any]) -> TestResult:
        """Legacy parsing for backward compatibility"""
        
        # Determine if test passed or failed
        failed = task_result.get('failed', False) or task_result.get('rc', 0) != 0
        
        # Check against expected_result if provided
        if test.expected_result:
            if test.expected_result == "success":
                passed = not failed
            elif test.expected_result == "failure":
                passed = failed
            else:
                # Try to match expected result in output
                output_text = str(task_result.get('stdout', '')) + str(task_result.get('msg', ''))
                passed = test.expected_result.lower() in output_text.lower()
        else:
            passed = not failed
        
        status = "passed" if passed else "failed"
        points_earned = test.points if passed else 0
        
        # Generate message
        if passed:
            message = f"Test passed: {task_result.get('msg', 'Success')}"
        else:
            error_msg = task_result.get('stderr', '') or task_result.get('msg', '') or 'Unknown error'
            message = f"Test failed: {error_msg}"
        
        return TestResult(
            test_name=test.name,
            status=status,
            message=message,
            points_earned=points_earned,
            points_possible=test.points,
            execution_time=event_data.get('duration', 0.0),
            extracted_data=extracted_data,
            raw_output=json.dumps(task_result, indent=2)
        )