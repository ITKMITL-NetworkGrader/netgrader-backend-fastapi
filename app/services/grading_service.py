import json
import yaml
import tempfile
import os
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any
from pathlib import Path
import ansible_runner
from jinja2 import Environment, FileSystemLoader
from app.schemas.models import (
    GradingJob, TestResult, GradingResult, ProgressUpdate, 
    ConnectionType, AnsibleTask, Play
)
from app.core.config import config
# from app.services.api_client import APIClient
from app.services.api_client_request import ApiClient
from app.services.scoring_service import ScoringService
# from app.services.data_parser import DataParser  # No longer needed with CLAUDE.md approach

logger = logging.getLogger(__name__)

class GradingService:
    """Core service that generates Ansible playbooks and executes grading jobs"""
    
    def __init__(self):
        self.api_client = ApiClient()
        self.scoring_service = ScoringService()
        # self.data_parser = DataParser()  # No longer needed
        self.templates_dir = Path(config.TEMPLATES_DIR)
        self.shared_tasks_dir = Path(config.SHARED_TASKS_DIR)
        self.jinja_env = Environment(loader=FileSystemLoader(self.templates_dir))
        
        # Ensure directories exist
        os.makedirs(config.ANSIBLE_INVENTORY_DIR, exist_ok=True)
        os.makedirs(config.ANSIBLE_PLAYBOOK_DIR, exist_ok=True)
        os.makedirs(config.SHARED_TASKS_DIR, exist_ok=True)
        
        # Setup shared tasks directory (copy templates once at startup)
        self._setup_shared_tasks_directory()
    
    def _setup_shared_tasks_directory(self):
        """Copy task templates to shared directory once at service startup"""
        import shutil
        
        src_tasks_dir = self.templates_dir / "tasks"
        
        # Check if we should preserve shared tasks across restarts
        if config.PRESERVE_SHARED_TASKS_ON_RESTART and self.shared_tasks_dir.exists():
            # Check if templates are up to date
            if self._are_shared_tasks_current(src_tasks_dir):
                logger.info(f"Preserving existing shared tasks directory at {self.shared_tasks_dir}")
                return
            else:
                logger.info("Shared tasks directory exists but templates are outdated, refreshing...")
        
        # Clear existing shared tasks directory (if not preserving or outdated)
        if self.shared_tasks_dir.exists():
            shutil.rmtree(self.shared_tasks_dir)
        self.shared_tasks_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy all task template files to shared location
        if src_tasks_dir.exists():
            templates_copied = 0
            for task_file in src_tasks_dir.glob("*.j2"):
                shutil.copy2(task_file, self.shared_tasks_dir / task_file.name)
                templates_copied += 1
                logger.debug(f"Copied task template to shared location: {task_file.name}")
            
            logger.info(f"Setup shared tasks directory with {templates_copied} templates at {self.shared_tasks_dir}")
        else:
            logger.warning(f"Source tasks directory not found: {src_tasks_dir}")
    
    def _are_shared_tasks_current(self, src_tasks_dir: Path) -> bool:
        """Check if shared tasks directory contains current versions of templates"""
        try:
            # Check if all source templates exist in shared directory
            for src_file in src_tasks_dir.glob("*.j2"):
                shared_file = self.shared_tasks_dir / src_file.name
                if not shared_file.exists():
                    logger.debug(f"Missing shared template: {src_file.name}")
                    return False
                
                # Check if source file is newer than shared file
                if src_file.stat().st_mtime > shared_file.stat().st_mtime:
                    logger.debug(f"Outdated shared template: {src_file.name}")
                    return False
            
            # Check if shared directory has extra files (deleted from source)
            for shared_file in self.shared_tasks_dir.glob("*.j2"):
                src_file = src_tasks_dir / shared_file.name
                if not src_file.exists():
                    logger.debug(f"Orphaned shared template: {shared_file.name}")
                    return False
            
            return True
            
        except Exception as e:
            logger.warning(f"Failed to check shared tasks currency: {e}")
            return False
    
    def _cleanup_job_files(self, job_id: str):
        """Clean up playbook and inventory files for a specific job"""
        try:
            # Clean up playbook file
            playbook_path = os.path.join(config.ANSIBLE_PLAYBOOK_DIR, f"playbook_{job_id}.yml")
            if os.path.exists(playbook_path):
                os.remove(playbook_path)
                logger.debug(f"Cleaned up playbook file: playbook_{job_id}.yml")
            
            # Clean up inventory file
            inventory_path = os.path.join(config.ANSIBLE_INVENTORY_DIR, f"inventory_{job_id}.yml")
            if os.path.exists(inventory_path):
                os.remove(inventory_path)
                logger.debug(f"Cleaned up inventory file: inventory_{job_id}.yml")
                
            logger.info(f"Successfully cleaned up files for job {job_id}")
            
        except Exception as e:
            logger.warning(f"Failed to cleanup files for job {job_id}: {e}")
    
    def cleanup_old_files(self):
        """Clean up old playbook and inventory files older than configured hours"""
        try:
            from datetime import timedelta
            import time
            
            cutoff_time = time.time() - (config.CLEANUP_FILES_OLDER_THAN_HOURS * 3600)
            cleaned_count = 0
            
            # Clean up old playbooks
            playbook_dir = Path(config.ANSIBLE_PLAYBOOK_DIR)
            if playbook_dir.exists():
                for file_path in playbook_dir.glob("playbook_*.yml"):
                    if file_path.stat().st_mtime < cutoff_time:
                        file_path.unlink()
                        cleaned_count += 1
                        logger.debug(f"Cleaned up old playbook: {file_path.name}")
            
            # Clean up old inventories
            inventory_dir = Path(config.ANSIBLE_INVENTORY_DIR)
            if inventory_dir.exists():
                for file_path in inventory_dir.glob("inventory_*.yml"):
                    if file_path.stat().st_mtime < cutoff_time:
                        file_path.unlink()
                        cleaned_count += 1
                        logger.debug(f"Cleaned up old inventory: {file_path.name}")
            
            if cleaned_count > 0:
                logger.info(f"Periodic cleanup removed {cleaned_count} old files (older than {config.CLEANUP_FILES_OLDER_THAN_HOURS}h)")
                
        except Exception as e:
            logger.error(f"Failed to perform periodic cleanup: {e}")
    
    async def process_grading_job(self, job: GradingJob) -> GradingResult:
        """Main method to process a grading job"""
        start_time = datetime.now()
        logger.info(f"Starting grading job {job.job_id} for student {job.student_id}")
        
        # Initialize result
        result = GradingResult(
            job_id=job.job_id,
            status="running",
            total_points_earned=0,
            total_points_possible=sum(task.points for task in job.part.play.ansible_tasks),
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
        
        # Cleanup job files after successful completion
        if result.status == "completed" and config.CLEANUP_FILES_AFTER_JOB:
            self._cleanup_job_files(job.job_id)
        
        logger.info(f"Completed grading job {job.job_id}. Score: {result.total_points_earned}/{result.total_points_possible}")
        return result
    
    async def _generate_inventory(self, job: GradingJob) -> str:
        """Generate Ansible inventory file for the lab topology with proxy support"""
        inventory = {
            "all": {
                "children": {
                    "network_devices": {"hosts": {}},
                    "linux_servers": {"hosts": {}},
                    "proxy_hosts": {"hosts": {}},
                    "proxy_targets": {"hosts": {}}
                }
            }
        }
        
        # Create device mapping for proxy host resolution
        device_map = {device.id: device for device in job.devices}
        
        for device in job.devices:
            host_config = {
                "ansible_host": device.ip_address,
                "ansible_connection": device.ansible_connection
            }
            # Add credentials from the credentials dict
            if device.credentials:
                host_config.update(device.credentials)
            if device.platform:
                host_config["ansible_network_os"] = device.platform
            
            # Handle proxy configuration for two-stage SSH
            if device.role == "proxy_target" and device.proxy_host:
                # Proxy target devices - handled by delegation
                if device.proxy_host in device_map:
                    proxy_host_device = device_map[device.proxy_host]
                    host_config["proxy_host"] = device.proxy_host
                    host_config["proxy_host_ip"] = proxy_host_device.ip_address
                    host_config["proxy_host_credentials"] = proxy_host_device.credentials
                    if device.proxy_credentials:
                        host_config["proxy_target_credentials"] = device.proxy_credentials
                    else:
                        host_config["proxy_target_credentials"] = device.credentials
                    
                    # Add SSH compatibility args for proxy connection
                    host_config["proxy_ssh_args"] = "-o StrictHostKeyChecking=no -o HostKeyAlgorithms=+ssh-rsa"
                    
                inventory["all"]["children"]["proxy_targets"]["hosts"][device.id] = host_config
                
            elif device.role == "proxy_host":
                # Proxy host devices - direct connection with SSH compatibility
                if device.ssh_args:
                    host_config["ansible_ssh_common_args"] = device.ssh_args
                else:
                    # Add default SSH compatibility for older devices
                    host_config["ansible_ssh_common_args"] = "-o StrictHostKeyChecking=no -o HostKeyAlgorithms=+ssh-rsa"
                
                inventory["all"]["children"]["proxy_hosts"]["hosts"][device.id] = host_config
                
            else:
                # Direct connection devices (legacy behavior)
                # Handle jump host configuration for isolated devices (backward compatibility)
                if device.jump_host and device.jump_host in device_map:
                    jump_host_device = device_map[device.jump_host]
                    self._configure_jump_host_connection(host_config, device, jump_host_device)
                
                # Handle persistent connections
                if device.use_persistent_connection:
                    host_config["ansible_persistent_connect_timeout"] = 60
                    host_config["ansible_command_timeout"] = 30
                
                # Add custom SSH arguments if specified
                if device.ssh_args:
                    if device.ansible_connection == "ssh":
                        host_config["ansible_ssh_common_args"] = device.ssh_args
                    elif device.ansible_connection == "ansible.netcommon.network_cli":
                        host_config["ansible_ssh_common_args"] = device.ssh_args
                
                # Add to appropriate group based on connection type
                if device.ansible_connection == "ansible.netcommon.network_cli":
                    inventory["all"]["children"]["network_devices"]["hosts"][device.id] = host_config
                else:
                    inventory["all"]["children"]["linux_servers"]["hosts"][device.id] = host_config
                    
        print(inventory)
        # Write inventory file
        inventory_path = os.path.join(config.ANSIBLE_INVENTORY_DIR, f"inventory_{job.job_id}.yml")
        with open(inventory_path, 'w') as f:
            yaml.dump(inventory, f, default_flow_style=False)
        
        logger.info(f"Generated inventory file: {inventory_path}")
        return inventory_path
    
    def _configure_jump_host_connection(self, host_config: Dict[str, Any], device: Any, jump_host_device: Any):
        """Configure jump host/proxy connection settings for isolated devices"""
        jump_host_ip = jump_host_device.ip_address
        
        # Build SSH proxy command arguments
        proxy_command_parts = []
        
        # Base SSH proxy command
        if device.ansible_connection == "ssh":
            # For SSH connections, use ProxyJump
            host_config["ansible_ssh_common_args"] = f"-o ProxyJump={jump_host_device.credentials.get('ansible_user', 'admin')}@{jump_host_ip}"
            
            # Handle SSH key exchange algorithms compatibility
            kex_args = "-o KexAlgorithms=+diffie-hellman-group1-sha1,diffie-hellman-group14-sha1"
            cipher_args = "-o Ciphers=+aes128-cbc,aes192-cbc,aes256-cbc"
            
            if device.ssh_args:
                host_config["ansible_ssh_common_args"] += f" {device.ssh_args}"
            else:
                host_config["ansible_ssh_common_args"] += f" {kex_args} {cipher_args}"
                
        elif device.ansible_connection == "ansible.netcommon.network_cli":
            # For network devices, set up proxy through SSH tunnel
            proxy_command = f"ssh -W %h:%p {jump_host_device.credentials.get('ansible_user', 'admin')}@{jump_host_ip}"
            host_config["ansible_ssh_common_args"] = f"-o ProxyCommand='{proxy_command}'"
            
            # Add compatibility settings
            kex_args = "-o KexAlgorithms=+diffie-hellman-group1-sha1,diffie-hellman-group14-sha1"
            host_config["ansible_ssh_common_args"] += f" {kex_args}"
        
        logger.info(f"Configured jump host connection for {device.id} through {jump_host_device.id}")
        logger.debug(f"Jump host SSH args: {host_config.get('ansible_ssh_common_args', 'none')}")
    
    async def _generate_playbook(self, job: GradingJob) -> str:
        """Generate the master Ansible playbook using hierarchical structure"""
        
        # Load and render master playbook template with proper context
        master_template = self.jinja_env.get_template("master_playbook.j2")
        playbook_content = master_template.render(
            part=job.part,
            ip_mappings=job.ip_mappings,
            shared_tasks_dir=config.SHARED_TASKS_DIR
        )
        
        # Write playbook file
        playbook_path = os.path.join(config.ANSIBLE_PLAYBOOK_DIR, f"playbook_{job.job_id}.yml")
        with open(playbook_path, 'w') as f:
            f.write(playbook_content)
        
        logger.info(f"Generated playbook file: {playbook_path}")
        return playbook_path
    
    # Old template generation methods removed - now using include_tasks in master playbook
    
    async def _execute_playbook(self, job: GradingJob, inventory_path: str, playbook_path: str, result: GradingResult) -> GradingResult:
        """Execute the Ansible playbook and parse results"""
        try:
            # Calculate total tasks for progress tracking
            total_tasks = len(job.part.play.ansible_tasks)
            
            # Send initial progress update
            if job.callback_url:
                progress = ProgressUpdate(
                    job_id=job.job_id,
                    status="executing",
                    message=f"Starting execution of part: {job.part.title}",
                    tests_completed=0,
                    total_tests=total_tasks,
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
        
        # No need to copy task templates - they are in shared directory
        # Templates are accessible via absolute path in include_tasks
        
        result = ansible_runner.run(
                playbook=playbook_path,
                inventory=inventory_path,
                private_data_dir=private_data_dir,
                quiet=False,
                verbosity=2
            )
        return result
    
    async def _parse_ansible_results(self, job: GradingJob, runner_result: Any, result: GradingResult) -> GradingResult:
        """Parse Ansible execution results and generate test results"""
        
        test_results = []
        tests_completed = 0
        
        # Process all ansible tasks from the single play in the part
        play = job.part.play
        all_tasks = [(task, play) for task in play.ansible_tasks]
        
        for task, play in all_tasks:
            test_result = TestResult(
                test_name=f"{play.play_id}_{task.task_id}",
                status="error",
                message="Task not executed",
                points_earned=0,
                points_possible=task.points,
                execution_time=0.0
            )
            
            # Look for set_fact events containing result_<task_id> in ansible_facts
            result_key = f"result_{task.task_id}"
            logger.debug(f"Looking for {result_key} in ansible events")
            
            for event in runner_result.events:
                event_type = event.get('event')
                if event_type in ['runner_on_ok', 'runner_on_failed']:
                    event_data = event.get('event_data', {})
                    task_result = event_data.get('res', {})
                    task_name = event_data.get('task', 'Unknown')
                    
                    # Debug: Log event details for troubleshooting
                    logger.debug(f"Event: {event_type}, Task: {task_name}, Has ansible_facts: {'ansible_facts' in task_result}")
                    
                    # Check if this event contains ansible_facts with our result_key
                    if 'ansible_facts' in task_result:
                        facts = task_result['ansible_facts']
                        fact_keys = list(facts.keys())
                        logger.debug(f"Available fact keys: {fact_keys}")
                        
                        if result_key in facts:
                            # Found the set_fact event for this task
                            test_result = self._parse_test_event(task, event, play)
                            logger.info(f"Found set_fact result for task '{task.task_id}': {test_result.status} ({test_result.points_earned}/{test_result.points_possible} points)")
                            break
            
            test_results.append(test_result)
            tests_completed += 1
            
            # Send progress update
            if job.callback_url:
                progress = ProgressUpdate(
                    job_id=job.job_id,
                    status="executing",
                    message=f"Completed task: {task.task_id}",
                    current_test=f"{play.play_id}_{task.task_id}",
                    tests_completed=tests_completed,
                    total_tests=len(all_tasks),
                    percentage=(tests_completed / len(all_tasks)) * 100
                )
                self.api_client.callback(job.callback_url, "/progress", progress.model_dump())
        
        result.test_results = test_results
        result.total_points_earned = sum(tr.points_earned for tr in test_results)
        
        logger.info(f"Final grading results: {result.total_points_earned}/{result.total_points_possible} points across {len(test_results)} tests")
        return result
    
    def _parse_test_event(self, task: AnsibleTask, event: Dict[str, Any], play: Play) -> TestResult:
        """Parse individual test result from Ansible event with advanced scoring"""
        event_data = event.get('event_data', {})
        task_result = event_data.get('res', {})
        
        # Extract data from ansible facts/variables using CLAUDE.md approach
        extracted_data = self._extract_test_data(event, task_result, task.task_id)
        logger.debug(f"Extracted Data for {task.task_id}: {list(extracted_data.keys())}")
        
        # Use new scoring system if test cases are defined
        if task.test_cases:
            logger.debug("Analyzing test cases with advanced scoring")
            test_case_results = self.scoring_service.evaluate_test_cases_for_task(task, extracted_data)
            points_earned, message = self.scoring_service.calculate_test_score(test_case_results, task.points)
            status = "passed" if points_earned > 0 else "failed"
            logger.debug(f"Test case results: points earned {points_earned}")
            return TestResult(
                test_name=f"{play.play_id}_{task.task_id}",
                status=status,
                message=message,
                points_earned=points_earned,
                points_possible=task.points,
                execution_time=event_data.get('duration', 0.0),
                test_case_results=test_case_results,
                extracted_data=extracted_data,
                raw_output=json.dumps(task_result, indent=2)
            )
        
        # Fallback to legacy scoring for backward compatibility
        else:
            logger.debug("Using legacy parsing (no test cases defined)")
            return self._legacy_parse_test_event(task, event_data, task_result, extracted_data, play)
    
    def _extract_test_data(self, event: Dict[str, Any], task_result: Dict[str, Any], task_id: str) -> Dict[str, Any]:
        """Extract test data using CLAUDE.md set_fact approach"""
        extracted_data = {}
        
        # Look for result_<task_id> in ansible_facts (CLAUDE.md approach)
        if 'ansible_facts' in task_result:
            facts = task_result['ansible_facts']
            result_key = f"result_{task_id}"
            logger.debug(f"Found ansible_facts in task_result, looking for {result_key}")
            
            if result_key in facts:
                result_data = facts[result_key]
                logger.info(f"Found {result_key} in ansible_facts")
                
                # Extract standardized fields
                extracted_data.update({
                    'status': result_data.get('status', 'unknown'),
                    'stdout': result_data.get('stdout', ''),
                    'stderr': result_data.get('stderr', ''),
                    'return_code': result_data.get('rc', 1),
                    'raw': result_data.get('raw', {}),
                    'success': result_data.get('status') == 'passed',
                    'failed': result_data.get('status') == 'failed'
                })
                
                # Include custom fields if present
                if 'custom' in result_data:
                    extracted_data.update(result_data['custom'])
                
                logger.info(f"Successfully extracted data from {result_key}: {list(extracted_data.keys())}")
                return extracted_data
        
        # Fallback: Extract basic command results from task_result
        logger.warning(f"No result_{task_id} found, using fallback extraction")
        stdout = task_result.get('stdout', '')
        stderr = task_result.get('stderr', '')
        rc = task_result.get('rc', 1)
        failed = task_result.get('failed', False)
        
        extracted_data = {
            'status': 'failed' if failed or rc != 0 else 'passed',
            'stdout': stdout,
            'stderr': stderr,
            'return_code': rc,
            'success': not failed and rc == 0,
            'failed': failed or rc != 0,
            'raw': task_result
        }
            
        logger.debug(f"Fallback extracted data keys: {list(extracted_data.keys())}")
        return extracted_data
    
    def _legacy_parse_test_event(self, task: AnsibleTask, event_data: Dict[str, Any], 
                                task_result: Dict[str, Any], extracted_data: Dict[str, Any], play: Play) -> TestResult:
        """Legacy parsing for backward compatibility"""
        
        # Determine if test passed or failed
        failed = task_result.get('failed', False) or task_result.get('rc', 0) != 0
        
        # For legacy support, assume success if no test cases defined
        passed = not failed
        status = "passed" if passed else "failed"
        points_earned = task.points if passed else 0
        
        # Generate message
        if passed:
            message = f"Test passed: {task_result.get('msg', 'Success')}"
        else:
            error_msg = task_result.get('stderr', '') or task_result.get('msg', '') or 'Unknown error'
            message = f"Test failed: {error_msg}"
        
        return TestResult(
            test_name=f"{play.play_id}_{task.task_id}",
            status=status,
            message=message,
            points_earned=points_earned,
            points_possible=task.points,
            execution_time=event_data.get('duration', 0.0),
            extracted_data=extracted_data,
            raw_output=json.dumps(task_result, indent=2)
        )