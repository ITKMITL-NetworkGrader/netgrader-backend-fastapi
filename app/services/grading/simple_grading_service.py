"""
Simple Grading Service - FastAPI Integration with Nornir

Integrates Nornir-based grading system with device detection for
automated network testing and grading.
"""

import logging
import time
from datetime import datetime
from typing import Dict, Any
# Import existing models and services
from app.schemas.models import GradingJob, TestResult, GradingResult, Device, NetworkTask, ProgressUpdate, DebugInfo, TaskGroup, GroupResult, TaskResult, TaskStatus, ConnectionType
from app.services.connectivity.api_client import APIClient as ApiClient
from app.services.grading.scoring_service import ScoringService

# Import our working components
from .nornir_grading_service import NornirGradingService
from app.services.connectivity.snmp_detection import DeviceDetectionService
from app.services.connectivity.minio_service import MinioService
from app.services.custom_tasks.custom_task_registry import CustomTaskRegistry
from app.core.config import config

logger = logging.getLogger(__name__)

class SimpleGradingService:
    """
    Nornir-based grading service that integrates with existing FastAPI infrastructure
    and includes automated device detection.
    """
    
    def __init__(self):
        self.api_client = ApiClient()
        self.scoring_service = ScoringService()
        self.grader = NornirGradingService()
        self._initialized = False
        self.callback_url = config.CALLBACK_URL
        # Initialize SNMP device detection service
        if config.SNMP_ENABLED:
            self.device_detector = DeviceDetectionService(
                snmp_community=config.SNMP_COMMUNITY,
                snmp_timeout=config.SNMP_TIMEOUT
            )
        else:
            self.device_detector = None
        
        # Initialize MinIO service for loading custom task templates
        self._minio_service = MinioService(
            bucket_name=config.MINIO_BUCKET_NAME,
            auto_create_bucket=True
        )
        
        # Initialize global task template registry (async initialization required)
        self.global_task_registry = CustomTaskRegistry(
            minio_service=self._minio_service,
            bucket_name=config.MINIO_BUCKET_NAME
        )
    
    async def initialize(self):
        """Initialize the grading service"""
        if self._initialized:
            return
        
        logger.info("Initializing Nornir Grading Service...")
        
        # Initialize global task template registry from MinIO
        await self.global_task_registry.initialize()
        logger.info(f"Loaded {len(self.global_task_registry.list_templates())} custom task templates from MinIO")
        
        # Set the registry on the grader for custom task execution
        self.grader.set_custom_task_registry(self.global_task_registry)
        
        # Nornir grader will initialize when needed
        logger.info("Nornir grading service ready")
        
        self._initialized = True
        logger.info("Nornir Grading Service initialized successfully")
    
    def _convert_device(self, device: Device, detection_results: Dict[str, Any] = None) -> Device:
        """Convert FastAPI Device model to Device with detection results"""
        
        # Determine device_type using detection results or fallback to platform
        device_type = "linux"  # Default
        
        if detection_results and device.id in detection_results:
            detected = detection_results[device.id]
            device_type = detected.get("device_type", device_type)
            
            # If device_type from detection is generic, try to infer from platform
            if device_type == "unknown" or device_type == "generic":
                if detected.get("platform"):
                    if "ios" in detected["platform"].lower():
                        device_type = "cisco_router"  # Default to router for IOS
                    elif "linux" in detected["platform"].lower():
                        device_type = "linux_server"
        
        # Fallback to platform-based detection if no detection results
        if device_type == "linux" and device.platform:
            if "telnet" in device.platform.lower():
                device_type = device.platform
            elif "ios" in device.platform.lower():
                device_type = "cisco_router"
            elif "linux" in device.platform.lower():
                device_type = "linux_server"
            else:
                device_type = device.platform
        
        return Device(
            id=device.id,
            ip_address=device.ip_address,
            credentials={
                "username": device.credentials.get("username", "admin"),
                "password": device.credentials.get("password", "")
            },
            platform=device_type,
            device_os=device.device_os,  # Preserve device_os field
            port=device.port if device.port else 22,
            connection_type=device.connection_type
        )
    
    def _format_error(self, raw_output: str) -> str:
        """
        Convert raw error messages to user-friendly format.
        
        Only transforms content that matches known error patterns.
        Normal output is returned unchanged.
        """
        if not raw_output:
            return raw_output
        
        error_lower = raw_output.lower()
        
        # Handle Netmiko ReadTimeout errors
        if "readtimeout" in error_lower or "pattern not detected" in error_lower:
            return "Connection timeout: The device did not respond within the expected time. This may indicate the device is unreachable, busy, or the command took too long to execute."
        
        # Handle authentication errors
        if "authentication" in error_lower and ("failed" in error_lower or "error" in error_lower):
            return "Authentication failed: Could not authenticate with the device. Please verify the credentials are correct."
        
        if "permission denied" in error_lower:
            return "Authentication failed: Permission denied. Please verify the credentials are correct."
        
        # Handle connection refused errors
        if "connection refused" in error_lower:
            return "Connection refused: The device actively refused the connection. Please verify the device is reachable and the service is running on the expected port."
        
        # Handle timeout errors (general) - but not just any mention of "timeout"
        if ("timeout" in error_lower or "timed out" in error_lower) and ("connection" in error_lower or "socket" in error_lower):
            return "Connection timeout: Could not establish a connection to the device within the allowed time."
        
        # Handle SSH key errors
        if "host key" in error_lower and ("verification" in error_lower or "failed" in error_lower or "error" in error_lower):
            return "SSH key verification failed: Could not verify the device's SSH host key."
        
        # Handle unreachable host errors
        if "no route to host" in error_lower or "host unreachable" in error_lower or "network unreachable" in error_lower:
            return "Network error: The device is unreachable. Please verify network connectivity."
        
        # Handle name resolution errors
        if "name or service not known" in error_lower or "could not resolve" in error_lower:
            return "DNS error: Could not resolve the device hostname. Please verify the hostname is correct."
        
        # Handle command execution errors with tracebacks
        if "traceback" in error_lower or "File \"" in raw_output:
            # This looks like a Python traceback - provide clean message
            if "readtimeout" in error_lower:
                return "Connection timeout: The device did not respond within the expected time."
            elif "authentication" in error_lower:
                return "Authentication failed: Could not authenticate with the device."
            elif "connection" in error_lower and "refused" in error_lower:
                return "Connection refused: The device refused the connection."
            else:
                return "An unexpected error occurred during task execution. Please check the device connectivity and configuration."
        
        # Handle system paths in output (security concern)
        if "/" in raw_output or "site-packages" in raw_output:
            return "An unexpected error occurred during task execution. Please check the device connectivity and configuration."
        
        # No error pattern matched - return original output unchanged
        return raw_output
    
    def _convert_task_result(self, task_result: TaskResult, task: NetworkTask) -> TestResult:
        """Convert TaskResult to FastAPI TestResult model"""
        # Check if task_result has debug_info attribute (for custom tasks)
        debug_info = None
        if hasattr(task_result, 'debug_info') and task_result.debug_info:
            debug_data = task_result.debug_info
            debug_info = DebugInfo(
                enabled=debug_data.get("enabled", False),
                parameters_received=debug_data.get("parameters_received"),
                registered_variables=debug_data.get("registered_variables"),
                command_results=debug_data.get("command_results"),
                validation_details=debug_data.get("validation_details"),
                custom_debug_points=debug_data.get("custom_debug_points")
            )
        # Format error messages to be user-friendly
        formatted_stdout = self._format_error(task_result.stdout)
        formatted_stderr = self._format_error(task_result.stderr)
        formatted_message = formatted_stderr if formatted_stderr else "Task completed successfully"
        
        return TestResult(
            test_name=task.task_id,
            status=task_result.status.value,
            points_earned=task_result.points_earned,
            points_possible=task_result.points_possible,
            execution_time=task_result.execution_time,
            message=formatted_message,
            test_case_results=[],  # Empty list for now, can be enhanced later
            extracted_data={
                "stdout": formatted_stdout,
                "stderr": formatted_stderr,
                "task_type": task.template_name,
                "execution_device": task.execution_device
            },
            raw_output=formatted_stdout,
            debug_info=debug_info,
            group_id=task.group_id
        )
    
    async def process_grading_job(self, job: GradingJob) -> GradingResult:
        """Process a grading job using the simple plugin system"""
        start_time = time.time()
        
        # Use per-job callback URL if provided (for playground jobs), otherwise fall back to global config
        callback_url = job.callback_url if job.callback_url else self.callback_url
        
        logger.info(f"Processing grading job: {job.job_id}")
        logger.info(f"Student: {job.student_id}, Lab: {job.lab_id}")
        logger.info(f"Part: {job.part.title}")
        if job.callback_url:
            logger.info(f"Using per-job callback URL: {callback_url}")
        
        # Send progress update
        if callback_url:
            try:
                progress = ProgressUpdate(
                    job_id=job.job_id,
                    status="started",
                    message="Initializing grading job",
                    tests_completed=0,
                    total_tests=len(job.part.network_tasks),
                    percentage=0.0
                )
                await self.api_client.send_progress_update(callback_url, progress)
            except Exception as e:
                logger.warning(f"Failed to send progress update: {e}")

        
        # Run device detection for devices without platform info
        detection_results = {}
        devices_needing_detection = [d for d in job.devices if not d.platform or d.platform.lower() == 'unknown']
        if devices_needing_detection:
            logger.info(f"Running device detection for {len(devices_needing_detection)} devices without platform info")
            if callback_url:
                try:
                    progress = ProgressUpdate(
                        job_id=job.job_id,
                        status="running",
                        message="Detecting device types and capabilities",
                        tests_completed=0,
                        total_tests=len(job.part.network_tasks),
                        percentage=5.0
                    )
                    await self.api_client.send_progress_update(callback_url, progress)
                except Exception as e:
                    logger.warning(f"Failed to send progress update: {e}")
            
            # Run device detection
            detection_results = await self.detect_devices(job)
            
            # Update device platforms based on detection results
            for device in job.devices:
                if device.id in detection_results:
                    detection_result = detection_results[device.id]
                    if detection_result.get('platform') and detection_result['platform'] != 'unknown':
                        original_platform = device.platform
                        device.platform = detection_result['platform']
                        if original_platform != device.platform:
                            logger.info(f"Updated {device.id} platform: {original_platform} -> {device.platform}")
        
        # Add devices to Nornir grader with detection results
        for device in job.devices:
            simple_device = self._convert_device(device, detection_results)
            await self.grader.add_device(simple_device)
        
        # Process tasks with group handling
        tasks = job.part.network_tasks
        groups = job.part.groups
        total_tasks = len(tasks)
        
        # Group tasks by group_id
        grouped_tasks = self.scoring_service.group_tasks_by_id(tasks)
        ungrouped_tasks = self.scoring_service.get_ungrouped_tasks(tasks)
        
        # Create group lookup for easier access
        group_lookup = {group.group_id: group for group in groups}
        
        # Track results
        test_results = []
        group_results = []
        total_points_possible = 0
        total_points_earned = 0
        execution_cancelled = False
        cancellation_reason = None
        
        task_index = 0
        
        # Process ungrouped tasks first
        logger.info(f"Processing {len(ungrouped_tasks)} ungrouped tasks")
        for task in ungrouped_tasks:
            if execution_cancelled:
                break
                
            task_index += 1
            logger.info(f"Processing task {task_index}/{total_tasks}: {task.task_id}")
            
            # Execute individual task
            test_result = await self._execute_single_task(task, job, task_index, total_tasks, callback_url=callback_url)
            test_results.append(test_result)
            
            total_points_possible += task.points
            total_points_earned += test_result.points_earned
        
        # Process task groups
        logger.info(f"Processing {len(grouped_tasks)} task groups")
        for group_id, group_tasks in grouped_tasks.items():
            if execution_cancelled:
                break
                
            group_config = group_lookup.get(group_id)
            if not group_config:
                logger.error(f"Group configuration not found for group_id: {group_id}")
                continue
            
            logger.info(f"Processing group: {group_config.title} ({len(group_tasks)} tasks)")
            
            # Execute all tasks in the group
            group_task_results = []
            group_start_time = time.time()
            
            for task in group_tasks:
                if execution_cancelled:
                    break
                    
                task_index += 1
                logger.info(f"Processing group task {task_index}/{total_tasks}: {task.task_id}")
                
                # Execute task (but don't count individual points yet)
                test_result = await self._execute_single_task(task, job, task_index, total_tasks, group_config.title, callback_url=callback_url)
                group_task_results.append(test_result)
                test_results.append(test_result)
            
            # Evaluate group
            if not execution_cancelled:
                group_result = self.scoring_service.evaluate_task_group(group_config, group_task_results)
                group_results.append(group_result)
                
                total_points_possible += group_config.points
                total_points_earned += group_result.points_earned
                
                # Log group result
                status_emoji = "✅" if group_result.status == "passed" else ("❌" if group_result.status == "failed" else "⚠️")
                logger.info(f"{status_emoji} Group {group_config.title}: {group_result.status} ({group_result.points_earned}/{group_config.points} pts)")
                
                # Check continue_on_failure
                if group_result.status == "failed" and not group_config.continue_on_failure:
                    execution_cancelled = True
                    cancellation_reason = f"Group '{group_config.title}' failed and continue_on_failure=false"
                    logger.warning(f"Cancelling execution: {cancellation_reason}")
                    
                    # Execute rescue tasks if defined
                    if group_config.rescue_tasks:
                        logger.info(f"Executing {len(group_config.rescue_tasks)} rescue tasks")
                        await self._execute_rescue_tasks(group_config.rescue_tasks, job)
                        group_result.rescue_executed = True
                    
                    # Execute cleanup tasks if defined
                    if group_config.cleanup_tasks:
                        logger.info(f"Executing {len(group_config.cleanup_tasks)} cleanup tasks")
                        await self._execute_cleanup_tasks(group_config.cleanup_tasks, job)
                        group_result.cleanup_executed = True
                else:
                    # Execute cleanup tasks for successful groups too (if defined)
                    if group_config.cleanup_tasks:
                        logger.info(f"Executing {len(group_config.cleanup_tasks)} cleanup tasks")
                        await self._execute_cleanup_tasks(group_config.cleanup_tasks, job)
                        group_result.cleanup_executed = True
        
        # Calculate final results
        total_execution_time = time.time() - start_time
        success_rate = (total_points_earned / total_points_possible * 100) if total_points_possible > 0 else 0
        
        # Determine overall status
        if execution_cancelled:
            status = "cancelled"
        elif total_points_earned == total_points_possible:
            status = "completed"
        elif total_points_earned > 0:
            status = "completed"
        else:
            status = "completed"
        
        # Create grading result
        result = GradingResult(
            job_id=job.job_id,
            status=status,
            total_points_possible=total_points_possible,
            total_points_earned=total_points_earned,
            total_execution_time=total_execution_time,
            test_results=test_results,
            group_results=group_results,
            created_at=datetime.now().isoformat(),
            completed_at=datetime.now().isoformat(),
            cancelled_reason=cancellation_reason
        )
        
        # Send final result
        if callback_url:
            try:
                # Send final progress update
                progress = ProgressUpdate(
                    job_id=job.job_id,
                    status="completed",
                    message=f"Grading completed: {total_points_earned}/{total_points_possible} points",
                    tests_completed=total_tasks,
                    total_tests=total_tasks,
                    percentage=100.0
                )
                await self.api_client.send_progress_update(callback_url, progress)
                
                # Send final result
                await self.api_client.send_final_result(callback_url, result)
            except Exception as e:
                logger.error(f"Failed to send final result: {e}")
        
        logger.info(f"Grading job completed: {total_points_earned}/{total_points_possible} points ({success_rate:.1f}%)")
        return result
    
    def _map_template_to_nornir_task(self, template_name: str) -> str:
        """Map template names to Nornir task types"""
        mapping = {
            "network_ping": "ping",
            "linux_ip_check": "command",
            "linux_remote_ssh": "ssh_test",  # Use specialized SSH connectivity test
            "network_ip_int": "napalm",
            "service_check": "command",
            "dhcp_check": "command",
            "route_check": "command",
            "network_acls_int": "napalm"
        }
        
        # Check if this is a global custom task template (direct task name)
        if self.global_task_registry.is_global_template(template_name):
            return "custom"
        
        # Legacy support: Check if this is a prefixed custom task
        if template_name.startswith("custom_"):
            return "custom"
        
        return mapping.get(template_name, "ping")  # Default to ping
    
    def _enhance_nornir_task_parameters(self, task: NetworkTask, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Enhance task parameters for Nornir execution"""
        enhanced = parameters.copy()
        
        # Handle global custom task templates (direct task name)
        if self.global_task_registry.is_global_template(task.template_name):
            # For global templates, use the template name directly as task ID
            enhanced["custom_task_id"] = task.template_name
            return enhanced
        
        # Legacy support: Handle prefixed custom instructor tasks
        elif task.template_name.startswith("custom_"):
            # For legacy custom tasks, extract the actual custom task ID from template name
            # Format: custom_<instructor_id>_<task_name>_<hash>
            custom_task_id = task.template_name[7:]  # Remove 'custom_' prefix
            enhanced["custom_task_id"] = custom_task_id
            return enhanced
        
        # Configure NAPALM operations for network interface checking
        elif task.template_name == "network_ip_int":
            # Use NAPALM to get interface information
            enhanced["operation"] = "get_interfaces_ip" if parameters.get("check_ip", False) else "get_interfaces"
            # Keep interface name and expected_ip as they are
            if "interface" in parameters:
                enhanced["interface"] = parameters["interface"]
            if "expected_ip" in parameters:
                enhanced["expected_ip"] = parameters["expected_ip"]
                enhanced["check_ip"] = True
        
        # Configure NAPALM operations for network ACL checking
        elif task.template_name == "network_acls_int":
            enhanced["operation"] = "get_interfaces"
        
        # Configure commands for SSH/command tests
        # elif task.template_name == "linux_remote_ssh":
        #     test_command = parameters.get("test_command", "whoami")
        #     target_ip = parameters.get("target_ip", "127.0.0.1")
        #     enhanced["command"] = f"{test_command}"
        
        elif task.template_name == "linux_ip_check":
            # Convert to appropriate command
            enhanced["command"] = parameters.get("command", "ip addr show")
            
        elif task.template_name == "service_check":
            service_name = parameters.get("service_name", "ssh")
            enhanced["command"] = f"systemctl status {service_name}"
            
        elif task.template_name == "dhcp_check":
            enhanced["command"] = parameters.get("command", "dhclient -v")
            
        elif task.template_name == "route_check":
            enhanced["command"] = parameters.get("command", "ip route show")
        
        return enhanced
    
    async def _execute_single_task(self, task: NetworkTask, job: GradingJob, task_index: int, total_tasks: int, group_name: str = None, callback_url: str = None) -> TestResult:
        """Execute a single task and return TestResult"""
        
        # Send progress update
        progress_value = (task_index / total_tasks) * 100.0
        if callback_url:
            try:
                message = f"Executing task: {task.task_id}"
                if group_name:
                    message += f" (Group: {group_name})"
                    
                progress = ProgressUpdate(
                    job_id=job.job_id,
                    status="running",
                    message=message,
                    tests_completed=task_index,
                    total_tests=total_tasks,
                    percentage=progress_value
                )
                await self.api_client.send_progress_update(callback_url, progress)
            except Exception as e:
                logger.warning(f"Failed to send progress update: {e}")
        
        # Map template names to Nornir task types
        task_type = self._map_template_to_nornir_task(task.template_name)
        
        # Execute task using Nornir
        # Convert task.parameters to dict if it's a model object
        if hasattr(task.parameters, '__dict__'):
            task_params = task.parameters.__dict__
        else:
            task_params = task.parameters if isinstance(task.parameters, dict) else {}
        
        # Convert job.ip_mappings to dict if it's a model object
        if hasattr(job.ip_mappings, '__dict__'):
            ip_mappings = job.ip_mappings.__dict__
        else:
            ip_mappings = job.ip_mappings if isinstance(job.ip_mappings, dict) else {}
        
        # Enhance parameters for specific task types
        enhanced_params = self._enhance_nornir_task_parameters(task, {
            **task_params,
            "points": task.points,
            # Add IP mappings for parameter resolution
            **ip_mappings
        })
        
        # Add execution mode parameters from task
        enhanced_params.update({
            "execution_mode": task.execution_mode,
            "stateful_session_id": task.stateful_session_id,
            "connection_timeout": task.connection_timeout
        })
        
        task_result = await self.grader.execute_task(
            task_id=task.task_id,
            task_type=task_type,
            device_id=task.execution_device,
            parameters=enhanced_params
        )
        
        # Convert to TestResult
        test_result = self._convert_task_result(task_result, task)
        
        # Log task result

        status_emoji = "✅" if task_result.status == TaskStatus.PASSED else ("❌" if task_result.status == TaskStatus.FAILED else "⚠️")
        group_suffix = f" (Group: {group_name})" if group_name else ""
        logger.info(f"{status_emoji} {task.task_id}: {task_result.status.value} ({task_result.points_earned}/{task.points} pts){group_suffix}")
        
        return test_result
    
    async def _execute_rescue_tasks(self, rescue_tasks: list, job: GradingJob):
        """Execute rescue tasks when a group fails"""
        logger.info("Executing rescue tasks...")
        
        for rescue_task in rescue_tasks:
            try:
                logger.info(f"Executing rescue task: {rescue_task.task_id}")
                
                # Execute rescue task (similar to regular task but don't affect scoring)
                task_type = self._map_template_to_nornir_task(rescue_task.template_name)
                
                if hasattr(rescue_task.parameters, '__dict__'):
                    task_params = rescue_task.parameters.__dict__
                else:
                    task_params = rescue_task.parameters if isinstance(rescue_task.parameters, dict) else {}
                
                if hasattr(job.ip_mappings, '__dict__'):
                    ip_mappings = job.ip_mappings.__dict__
                else:
                    ip_mappings = job.ip_mappings if isinstance(job.ip_mappings, dict) else {}
                
                enhanced_params = self._enhance_nornir_task_parameters(rescue_task, {
                    **task_params,
                    **ip_mappings
                })
                
                task_result = await self.grader.execute_task(
                    task_id=rescue_task.task_id,
                    task_type=task_type,
                    device_id=rescue_task.execution_device,
                    parameters=enhanced_params
                )
                
                logger.info(f"Rescue task {rescue_task.task_id} completed with status: {task_result.status.value}")
                
            except Exception as e:
                logger.error(f"Rescue task {rescue_task.task_id} failed: {e}")
    
    async def _execute_cleanup_tasks(self, cleanup_tasks: list, job: GradingJob):
        """Execute cleanup tasks (similar to rescue but always runs)"""
        logger.info("Executing cleanup tasks...")
        
        for cleanup_task in cleanup_tasks:
            try:
                logger.info(f"Executing cleanup task: {cleanup_task.task_id}")
                
                # Execute cleanup task (similar to regular task but don't affect scoring)
                task_type = self._map_template_to_nornir_task(cleanup_task.template_name)
                
                if hasattr(cleanup_task.parameters, '__dict__'):
                    task_params = cleanup_task.parameters.__dict__
                else:
                    task_params = cleanup_task.parameters if isinstance(cleanup_task.parameters, dict) else {}
                
                if hasattr(job.ip_mappings, '__dict__'):
                    ip_mappings = job.ip_mappings.__dict__
                else:
                    ip_mappings = job.ip_mappings if isinstance(job.ip_mappings, dict) else {}
                
                enhanced_params = self._enhance_nornir_task_parameters(cleanup_task, {
                    **task_params,
                    **ip_mappings
                })
                
                task_result = await self.grader.execute_task(
                    task_id=cleanup_task.task_id,
                    task_type=task_type,
                    device_id=cleanup_task.execution_device,
                    parameters=enhanced_params
                )
                
                logger.info(f"Cleanup task {cleanup_task.task_id} completed with status: {task_result.status.value}")
                
            except Exception as e:
                logger.error(f"Cleanup task {cleanup_task.task_id} failed: {e}")
    
    async def validate_job_payload(self, job: GradingJob) -> Dict[str, Any]:
        """Validate a job payload"""
        errors = []
        
        # Basic validation
        if not job.job_id:
            errors.append("job_id is required")
        
        if not job.student_id:
            errors.append("student_id is required")
        
        if not job.devices:
            errors.append("At least one device is required")
        
        if not job.part.network_tasks:
            errors.append("At least one task is required")
        
        # Check if task types are supported
        supported_templates = ["network_ping", "linux_ip_check", "linux_remote_ssh", 
                              "network_ip_int", "service_check", "dhcp_check", 
                              "route_check", "network_acls_int"]
        for task in job.part.network_tasks:
            # Allow built-in templates, global custom templates, or legacy prefixed custom templates
            if not (task.template_name in supported_templates or 
                    self.global_task_registry.is_global_template(task.template_name) or
                    task.template_name.startswith("custom_")):
                errors.append(f"Template not supported: {task.template_name}")
        
        # Validate task groups
        if job.part.groups:
            group_ids = {group.group_id for group in job.part.groups}
            task_group_ids = {task.group_id for task in job.part.network_tasks if task.group_id}
            
            # Check for tasks referencing non-existent groups
            invalid_group_refs = task_group_ids - group_ids
            if invalid_group_refs:
                errors.append(f"Tasks reference undefined groups: {', '.join(invalid_group_refs)}")
            
            # Check for empty groups (groups with no tasks)
            empty_groups = group_ids - task_group_ids
            if empty_groups:
                errors.append(f"Groups have no tasks assigned: {', '.join(empty_groups)}")
            
            # Validate group types
            for group in job.part.groups:
                if group.group_type not in ["all_or_nothing", "proportional"]:
                    errors.append(f"Invalid group_type '{group.group_type}' for group {group.group_id}")
                
                if group.points <= 0:
                    errors.append(f"Group {group.group_id} must have positive points")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors
        }
    
    async def test_connectivity(self, job: GradingJob) -> Dict[str, bool]:
        """Test basic connectivity to all devices"""
        logger.info("Testing connectivity to devices...")
        
        connectivity = {}
        
        # Add a localhost device for testing
        localhost = Device(
            id="test_localhost",
            ip_address="localhost",
            credentials={"username": "test", "password": "test"},
            platform="linux",
            connection_type=ConnectionType.LOCAL
        )
        await self.grader.add_device(localhost)
        
        for device in job.devices:
            try:
                # Test basic ping connectivity
                result = await self.grader.execute_plugin_task(
                    task_id=f"connectivity_test_{device.id}",
                    plugin_name="ping",
                    device_id="test_localhost",
                    parameters={"target_ip": device.ip_address, "ping_count": 1, "points": 1}
                )
                
                connectivity[device.id] = result.status == TaskStatus.PASSED
                
                if connectivity[device.id]:
                    logger.info(f"✅ Device {device.id} ({device.ip_address}) is reachable")
                else:
                    logger.warning(f"❌ Device {device.id} ({device.ip_address}) is not reachable")
                    
            except Exception as e:
                logger.error(f"❌ Connectivity test failed for {device.id}: {e}")
                connectivity[device.id] = False
        
        return connectivity
    
    async def detect_devices(self, job: GradingJob) -> Dict[str, Dict[str, Any]]:
        """Enhanced device detection with SNMP support and static fallback"""
        logger.info("Starting enhanced device detection...")
        
        detection_results = {}
        
        # Try SNMP detection if enabled
        if self.device_detector and config.SNMP_ENABLED:
            try:
                logger.info("Attempting SNMP-based device detection...")
                
                # Convert devices to the format expected by DeviceDetectionService
                device_list = []
                for device in job.devices:
                    device_list.append({
                        'id': device.id,
                        'ip_address': device.ip_address,
                        'platform': device.platform,
                        'credentials': device.credentials
                    })
                
                # Perform enhanced SNMP detection
                snmp_results = await self.device_detector.enhanced_detect_devices(device_list)
                
                if snmp_results:
                    logger.info(f"SNMP detection successful for {len(snmp_results)} devices")
                    detection_results.update(snmp_results)
                
                # Add smart plugin selection based on SNMP detection
                for device_id, result in detection_results.items():
                    if 'optimal_plugins' in result:
                        logger.debug(f"Device {device_id} optimal plugins: {result['optimal_plugins']}")
                
            except Exception as e:
                logger.error(f"SNMP device detection failed: {e}")
                logger.info("Falling back to static device detection")
                detection_results = {}
        
        # Fallback to static detection for any devices not detected via SNMP
        for device in job.devices:
            if device.id not in detection_results:
                logger.debug(f"Using static detection for device {device.id}")
                
                # Enhanced static detection with more intelligence
                if device.platform and "ios" in device.platform.lower():
                    detection_results[device.id] = {
                        "detection_method": "static",
                        "platform": "cisco_ios",
                        "vendor": "Cisco",
                        "model": "Unknown",
                        "device_type": "cisco_router",
                        "os_version": "Unknown",
                        "snmp_enabled": False,
                        "optimal_plugins": ["napalm", "ping", "command"],
                        "detection_time": 0.0,
                        "raw_data": {}
                    }
                elif device.platform and "linux" in device.platform.lower():
                    detection_results[device.id] = {
                        "detection_method": "static",
                        "platform": "linux",
                        "vendor": "Linux",
                        "model": "Generic",
                        "device_type": "linux_server",
                        "os_version": "Unknown",
                        "snmp_enabled": False,
                        "optimal_plugins": ["command", "ping"],
                        "detection_time": 0.0,
                        "raw_data": {}
                    }
                else:
                    # Generic fallback
                    detection_results[device.id] = {
                        "detection_method": "static", 
                        "platform": "generic",
                        "vendor": "Unknown",
                        "model": "Unknown",
                        "device_type": "unknown",
                        "os_version": "Unknown",
                        "snmp_enabled": False,
                        "optimal_plugins": ["ping", "command"],
                        "detection_time": 0.0,
                        "raw_data": {}
                    }
        
        # Log detection summary
        snmp_count = sum(1 for r in detection_results.values() if r.get('detection_method') == 'snmp')
        static_count = sum(1 for r in detection_results.values() if r.get('detection_method') == 'static')
        
        logger.info(f"Device detection completed: {snmp_count} via SNMP, {static_count} via static detection")
        return detection_results
    
    async def cleanup_old_files(self):
        """Clean up temporary files created by Nornir grading service"""
        if self.grader:
            await self.grader.cleanup()
        logger.info("Cleanup completed - Nornir temporary files cleaned")