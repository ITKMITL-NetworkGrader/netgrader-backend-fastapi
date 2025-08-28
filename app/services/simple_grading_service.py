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
from app.schemas.models import GradingJob, TestResult, GradingResult, Device, AnsibleTask, ProgressUpdate, DebugInfo
from app.services.api_client import APIClient as ApiClient
from app.services.scoring_service import ScoringService

# Import our working components
from .nornir_grading_service import NornirGradingService
from .network_grader import Device as SimpleDevice, TaskResult, TaskStatus
from .snmp_detection import DeviceDetectionService
from .custom_task_registry import CustomTaskRegistry
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
        
        # Initialize SNMP device detection service
        if config.SNMP_ENABLED:
            self.device_detector = DeviceDetectionService(
                snmp_community=config.SNMP_COMMUNITY,
                snmp_timeout=config.SNMP_TIMEOUT
            )
        else:
            self.device_detector = None
        
        # Initialize global task template registry
        self.global_task_registry = CustomTaskRegistry(config.CUSTOM_TASK_REGISTRY_DIR)
    
    async def initialize(self):
        """Initialize the grading service"""
        if self._initialized:
            return
        
        logger.info("Initializing Nornir Grading Service...")
        
        # Nornir grader will initialize when needed
        logger.info("Nornir grading service ready")
        
        self._initialized = True
        logger.info("Nornir Grading Service initialized successfully")
    
    def _convert_device(self, device: Device, detection_results: Dict[str, Any] = None) -> SimpleDevice:
        """Convert FastAPI Device model to SimpleDevice with detection results"""
        
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
            if "ios" in device.platform.lower():
                device_type = "cisco_router"
            elif "linux" in device.platform.lower():
                device_type = "linux_server"
        
        return SimpleDevice(
            id=device.id,
            ip_address=device.ip_address,
            username=device.credentials.get("ansible_user", "admin"),
            password=device.credentials.get("ansible_password", ""),
            device_type=device_type
        )
    
    def _convert_task_result(self, task_result: TaskResult, task: AnsibleTask) -> TestResult:
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
        
        return TestResult(
            test_name=task.task_id,
            status=task_result.status.value,
            points_earned=task_result.points_earned,
            points_possible=task_result.points_possible,
            execution_time=task_result.execution_time,
            message=task_result.stderr if task_result.stderr else "Task completed successfully",
            test_case_results=[],  # Empty list for now, can be enhanced later
            extracted_data={
                "stdout": task_result.stdout,
                "stderr": task_result.stderr,
                "task_type": task.template_name,
                "execution_device": task.execution_device
            },
            raw_output=task_result.stdout,
            debug_info=debug_info
        )
    
    async def process_grading_job(self, job: GradingJob) -> GradingResult:
        """Process a grading job using the simple plugin system"""
        start_time = time.time()
        
        logger.info(f"Processing grading job: {job.job_id}")
        logger.info(f"Student: {job.student_id}, Lab: {job.lab_id}")
        logger.info(f"Part: {job.part.title}")
        
        # Send progress update
        if job.callback_url:
            try:
                progress = ProgressUpdate(
                    job_id=job.job_id,
                    status="started",
                    message="Initializing grading job",
                    tests_completed=0,
                    total_tests=len(job.part.play.ansible_tasks),
                    percentage=0.0
                )
                await self.api_client.send_progress_update(job.callback_url, progress)
            except Exception as e:
                logger.warning(f"Failed to send progress update: {e}")
        
        # Run device detection for devices without platform info
        detection_results = {}
        devices_needing_detection = [d for d in job.devices if not d.platform or d.platform.lower() == 'unknown']
        if devices_needing_detection:
            logger.info(f"Running device detection for {len(devices_needing_detection)} devices without platform info")
            if job.callback_url:
                try:
                    progress = ProgressUpdate(
                        job_id=job.job_id,
                        status="running",
                        message="Detecting device types and capabilities",
                        tests_completed=0,
                        total_tests=len(job.part.play.ansible_tasks),
                        percentage=5.0
                    )
                    await self.api_client.send_progress_update(job.callback_url, progress)
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
        
        # Process tasks
        tasks = job.part.play.ansible_tasks
        total_tasks = len(tasks)
        test_results = []
        total_points_possible = 0
        total_points_earned = 0
        
        for i, task in enumerate(tasks):
            logger.info(f"Processing task {i+1}/{total_tasks}: {task.task_id}")
            
            # Send progress update
            progress_value = (i / total_tasks) * 100.0  # Convert to percentage
            if job.callback_url:
                try:
                    progress = ProgressUpdate(
                        job_id=job.job_id,
                        status="running",
                        message=f"Executing task: {task.task_id}",
                        tests_completed=i,
                        total_tests=total_tasks,
                        percentage=progress_value
                    )
                    await self.api_client.send_progress_update(job.callback_url, progress)
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
            task_result = await self.grader.execute_task(
                task_id=task.task_id,
                task_type=task_type,
                device_id=task.execution_device,
                parameters=enhanced_params
            )
            # Convert to TestResult
            test_result = self._convert_task_result(task_result, task)
            test_results.append(test_result)
            
            total_points_possible += task.points
            total_points_earned += task_result.points_earned
            
            # Log task result
            status_emoji = "✅" if task_result.status == TaskStatus.PASSED else ("❌" if task_result.status == TaskStatus.FAILED else "⚠️")
            logger.info(f"{status_emoji} {task.task_id}: {task_result.status.value} ({task_result.points_earned}/{task.points} pts)")
        
        # Calculate final results
        total_execution_time = time.time() - start_time
        success_rate = (total_points_earned / total_points_possible * 100) if total_points_possible > 0 else 0
        
        # Determine overall status
        if total_points_earned == total_points_possible:
            status = "completed_success"
        elif total_points_earned > 0:
            status = "completed_partial"
        else:
            status = "completed_failure"
        
        # Create grading result
        result = GradingResult(
            job_id=job.job_id,
            status=status,
            total_points_possible=total_points_possible,
            total_points_earned=total_points_earned,
            total_execution_time=total_execution_time,
            test_results=test_results,
            created_at=datetime.now().isoformat(),
            completed_at=datetime.now().isoformat()
        )
        
        # Send final result
        if job.callback_url:
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
                await self.api_client.send_progress_update(job.callback_url, progress)
                
                # Send final result
                await self.api_client.send_final_result(job.callback_url, result)
            except Exception as e:
                logger.error(f"Failed to send final result: {e}")
        
        logger.info(f"Grading job completed: {total_points_earned}/{total_points_possible} points ({success_rate:.1f}%)")
        return result
    
    def _map_template_to_nornir_task(self, template_name: str) -> str:
        """Map Ansible template names to Nornir task types"""
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
    
    def _enhance_nornir_task_parameters(self, task: AnsibleTask, parameters: Dict[str, Any]) -> Dict[str, Any]:
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
        
        if not job.part.play.ansible_tasks:
            errors.append("At least one task is required")
        
        # Check if task types are supported
        supported_templates = ["network_ping", "linux_ip_check", "linux_remote_ssh", 
                              "network_ip_int", "service_check", "dhcp_check", 
                              "route_check", "network_acls_int"]
        for task in job.part.play.ansible_tasks:
            # Allow built-in templates, global custom templates, or legacy prefixed custom templates
            if not (task.template_name in supported_templates or 
                    self.global_task_registry.is_global_template(task.template_name) or
                    task.template_name.startswith("custom_")):
                errors.append(f"Template not supported: {task.template_name}")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors
        }
    
    async def test_connectivity(self, job: GradingJob) -> Dict[str, bool]:
        """Test basic connectivity to all devices"""
        logger.info("Testing connectivity to devices...")
        
        connectivity = {}
        
        # Add a localhost device for testing
        localhost = SimpleDevice(
            id="test_localhost",
            ip_address="localhost",
            username="test",
            password="test",
            device_type="linux"
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
    
    def cleanup_old_files(self):
        """Clean up temporary files created by Nornir grading service"""
        if self.grader:
            self.grader.cleanup()
        logger.info("Cleanup completed - Nornir temporary files cleaned")