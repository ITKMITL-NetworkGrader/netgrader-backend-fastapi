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
    Device, TestDefinition, ConnectionType
)
from app.core.config import config
# from app.services.api_client import APIClient
from app.services.api_client_request import ApiClient

logger = logging.getLogger(__name__)

class GradingService:
    """Core service that generates Ansible playbooks and executes grading jobs"""
    
    def __init__(self):
        self.api_client = ApiClient()
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
            execution_time=0.0,
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
        result.execution_time = (end_time - start_time).total_seconds()
        # Send final result
        if job.callback_url:
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
            for event in runner_result.events:
                if event.get('event') == 'runner_on_ok' or event.get('event') == 'runner_on_failed':
                    task_name = event.get('event_data', {}).get('task', '')
                    if test.name in task_name:
                        test_result = self._parse_test_event(test, event)
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
        print(result)
        return result
    
    def _parse_test_event(self, test: TestDefinition, event: Dict[str, Any]) -> TestResult:
        """Parse individual test result from Ansible event"""
        event_data = event.get('event_data', {})
        task_result = event_data.get('res', {})
        
        # Determine if test passed or failed
        failed = event.get('event') == 'runner_on_failed' or task_result.get('failed', False)

        if failed:
            status = "failed"
            points_earned = 0
            message = task_result.get('msg', 'Test failed')
        else:
            status = "passed"
            points_earned = test.points
            message = task_result.get('msg', 'Test passed')
        
        return TestResult(
            test_name=test.name,
            status=status,
            message=message,
            points_earned=points_earned,
            points_possible=test.points,
            execution_time=event_data.get('duration', 0.0),
            raw_output=json.dumps(task_result, indent=2)
        )