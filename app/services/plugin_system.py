"""
Plugin System - Building on the working network grader

Adds a plugin architecture to the network grader without
complex dependencies or async complications.
"""

import json
import yaml
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from enum import Enum

# Import our working base
from .network_grader import NetworkGrader, Device, TaskResult, TaskStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BasePlugin(ABC):
    """Base class for all plugins"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Plugin name"""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Plugin description"""
        pass
    
    @abstractmethod
    async def execute(self, device: Device, parameters: Dict[str, Any]) -> TaskResult:
        """Execute the plugin task"""
        pass
    
    def validate_parameters(self, parameters: Dict[str, Any]) -> List[str]:
        """Validate parameters - return list of errors"""
        return []

class PingPlugin(BasePlugin):
    """Ping plugin"""
    
    @property
    def name(self) -> str:
        return "ping"
    
    @property
    def description(self) -> str:
        return "Basic ping connectivity test"
    
    def validate_parameters(self, parameters: Dict[str, Any]) -> List[str]:
        errors = []
        if "target_ip" not in parameters:
            errors.append("target_ip is required")
        return errors
    
    async def execute(self, device: Device, parameters: Dict[str, Any]) -> TaskResult:
        """Execute ping test"""
        import subprocess
        import time
        
        start_time = time.time()
        target_ip = parameters.get("target_ip")
        ping_count = parameters.get("ping_count", 3)
        
        try:
            cmd = ["ping", "-c", str(ping_count), target_ip]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            execution_time = time.time() - start_time
            success = result.returncode == 0 and "0% packet loss" in result.stdout
            
            return TaskResult(
                task_id=parameters.get("task_id", "ping_test"),
                status=TaskStatus.PASSED if success else TaskStatus.FAILED,
                stdout=result.stdout,
                stderr=result.stderr,
                execution_time=execution_time,
                points_earned=parameters.get("points", 10) if success else 0,
                points_possible=parameters.get("points", 10)
            )
            
        except Exception as e:
            return TaskResult(
                task_id=parameters.get("task_id", "ping_test"),
                status=TaskStatus.ERROR,
                stderr=str(e),
                execution_time=time.time() - start_time,
                points_earned=0,
                points_possible=parameters.get("points", 10)
            )

class NAPALMPlugin(BasePlugin):
    """NAPALM-based network device plugin"""
    
    @property
    def name(self) -> str:
        return "napalm"
    
    @property
    def description(self) -> str:
        return "Execute NAPALM operations on network devices"
    
    def validate_parameters(self, parameters: Dict[str, Any]) -> List[str]:
        errors = []
        if "operation" not in parameters:
            errors.append("operation is required (e.g., 'get_interfaces', 'get_interfaces_ip')")
        return errors
    
    async def execute(self, device: Device, parameters: Dict[str, Any]) -> TaskResult:
        """Execute NAPALM operation on network device"""
        import time
        
        start_time = time.time()
        operation = parameters.get("operation", "get_interfaces")
        
        try:
            # Import NAPALM
            from napalm import get_network_driver
            
            # Determine device driver
            if device.device_type == "cisco" or "ios" in device.device_type.lower():
                driver_name = "ios"
            else:
                driver_name = "ios"  # Default to IOS for now
            
            # Get the driver
            driver = get_network_driver(driver_name)
            
            # Create device connection
            napalm_device = driver(
                hostname=device.ip_address,
                username=device.username,
                password=device.password,
                optional_args={"transport": "ssh"}
            )
            
            # Connect to device
            napalm_device.open()
            
            # Execute the requested operation
            if operation == "get_interfaces":
                result_data = napalm_device.get_interfaces()
            elif operation == "get_interfaces_ip":
                result_data = napalm_device.get_interfaces_ip()
            elif operation == "get_facts":
                result_data = napalm_device.get_facts()
            else:
                # Try to call the method dynamically
                method = getattr(napalm_device, operation, None)
                if method:
                    result_data = method()
                else:
                    raise ValueError(f"Unknown NAPALM operation: {operation}")
            
            # Close connection
            napalm_device.close()
            
            # Process results for interface checking
            success = True
            stdout_lines = []
            
            if operation == "get_interfaces" or operation == "get_interfaces_ip":
                interface_name = parameters.get("interface", "")
                expected_ip = parameters.get("expected_ip", "")
                check_ip = parameters.get("check_ip", False)
                
                if interface_name:
                    # Check specific interface
                    if operation == "get_interfaces":
                        interface_data = result_data.get(interface_name, {})
                        is_up = interface_data.get("is_up", False)
                        is_enabled = interface_data.get("is_enabled", False)
                        
                        stdout_lines.append(f"Interface {interface_name}:")
                        stdout_lines.append(f"  Operational: {is_up}")
                        stdout_lines.append(f"  Enabled: {is_enabled}")
                        
                        # Set success based on operational status
                        success = is_up and is_enabled
                        
                    elif operation == "get_interfaces_ip":
                        interface_ips = result_data.get(interface_name, {})
                        
                        stdout_lines.append(f"Interface {interface_name} IP addresses:")
                        for ip_addr, ip_data in interface_ips.get("ipv4", {}).items():
                            stdout_lines.append(f"  {ip_addr}/{ip_data.get('prefix_length', 'unknown')}")
                        
                        if check_ip and expected_ip:
                            # Check if expected IP is present
                            has_expected_ip = expected_ip in interface_ips.get("ipv4", {})
                            success = has_expected_ip
                            if not has_expected_ip:
                                stdout_lines.append(f"  Expected IP {expected_ip} not found!")
                        else:
                            # Just check if interface has any IPs
                            success = len(interface_ips.get("ipv4", {})) > 0
                else:
                    # List all interfaces
                    stdout_lines.append("All interfaces:")
                    for iface, data in result_data.items():
                        if operation == "get_interfaces":
                            status = "UP" if data.get("is_up") else "DOWN"
                            stdout_lines.append(f"  {iface}: {status}")
                        elif operation == "get_interfaces_ip":
                            ips = list(data.get("ipv4", {}).keys())
                            ip_str = ", ".join(ips) if ips else "No IPs"
                            stdout_lines.append(f"  {iface}: {ip_str}")
            else:
                # Generic output for other operations
                stdout_lines.append(f"NAPALM {operation} result:")
                stdout_lines.append(str(result_data))
            
            return TaskResult(
                task_id=parameters.get("task_id", "napalm_test"),
                status=TaskStatus.PASSED if success else TaskStatus.FAILED,
                stdout="\n".join(stdout_lines),
                stderr="",
                execution_time=time.time() - start_time,
                points_earned=parameters.get("points", 10) if success else 0,
                points_possible=parameters.get("points", 10)
            )
            
        except Exception as e:
            return TaskResult(
                task_id=parameters.get("task_id", "napalm_test"),
                status=TaskStatus.ERROR,
                stderr=f"NAPALM operation failed: {str(e)}",
                execution_time=time.time() - start_time,
                points_earned=0,
                points_possible=parameters.get("points", 10)
            )

class CommandPlugin(BasePlugin):
    """Command execution plugin"""
    
    @property
    def name(self) -> str:
        return "command"
    
    @property
    def description(self) -> str:
        return "Execute system commands"
    
    def validate_parameters(self, parameters: Dict[str, Any]) -> List[str]:
        errors = []
        if "command" not in parameters:
            errors.append("command is required")
        return errors
    
    async def execute(self, device: Device, parameters: Dict[str, Any]) -> TaskResult:
        """Execute command"""
        import subprocess
        import time
        
        start_time = time.time()
        command = parameters.get("command")
        
        try:
            result = subprocess.run(command.split(), capture_output=True, text=True, timeout=30)
            
            execution_time = time.time() - start_time
            success = result.returncode == 0
            
            return TaskResult(
                task_id=parameters.get("task_id", "command_test"),
                status=TaskStatus.PASSED if success else TaskStatus.FAILED,
                stdout=result.stdout,
                stderr=result.stderr,
                execution_time=execution_time,
                points_earned=parameters.get("points", 10) if success else 0,
                points_possible=parameters.get("points", 10)
            )
            
        except Exception as e:
            return TaskResult(
                task_id=parameters.get("task_id", "command_test"),
                status=TaskStatus.ERROR,
                stderr=str(e),
                execution_time=time.time() - start_time,
                points_earned=0,
                points_possible=parameters.get("points", 10)
            )

class PluginManager:
    """Plugin manager"""
    
    def __init__(self):
        self.plugins: Dict[str, BasePlugin] = {}
        self.load_builtin_plugins()
    
    def load_builtin_plugins(self):
        """Load built-in plugins"""
        builtin_plugins = [
            PingPlugin(),
            CommandPlugin(),
            NAPALMPlugin()
        ]
        
        for plugin in builtin_plugins:
            self.register_plugin(plugin)
            logger.info(f"Loaded builtin plugin: {plugin.name}")
    
    def register_plugin(self, plugin: BasePlugin):
        """Register a plugin"""
        self.plugins[plugin.name] = plugin
    
    def get_plugin(self, name: str) -> Optional[BasePlugin]:
        """Get a plugin by name"""
        return self.plugins.get(name)
    
    def list_plugins(self) -> List[str]:
        """List all plugin names"""
        return list(self.plugins.keys())
    
    def load_yaml_plugin(self, yaml_file: str) -> bool:
        """Load a YAML-defined plugin"""
        try:
            with open(yaml_file, 'r') as f:
                config = yaml.safe_load(f)
            
            plugin = YAMLPlugin(config)
            self.register_plugin(plugin)
            logger.info(f"Loaded YAML plugin: {plugin.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load YAML plugin {yaml_file}: {e}")
            return False

class YAMLPlugin(BasePlugin):
    """Plugin created from YAML configuration"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
    
    @property
    def name(self) -> str:
        return self.config.get("name", "yaml_plugin")
    
    @property
    def description(self) -> str:
        return self.config.get("description", "YAML-defined plugin")
    
    def validate_parameters(self, parameters: Dict[str, Any]) -> List[str]:
        errors = []
        required_params = self.config.get("required_parameters", [])
        
        for param in required_params:
            if param not in parameters:
                errors.append(f"{param} is required")
        
        return errors
    
    async def execute(self, device: Device, parameters: Dict[str, Any]) -> TaskResult:
        """Execute YAML-defined steps"""
        import subprocess
        import time
        
        start_time = time.time()
        steps = self.config.get("steps", [])
        
        all_output = []
        all_errors = []
        overall_success = True
        
        for step in steps:
            step_type = step.get("type")
            
            if step_type == "ping":
                target_ip = step.get("target_ip", parameters.get("target_ip"))
                ping_count = step.get("ping_count", 3)
                
                try:
                    cmd = ["ping", "-c", str(ping_count), target_ip]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                    
                    all_output.append(f"Step {step.get('name', 'ping')}: {result.stdout}")
                    if result.stderr:
                        all_errors.append(result.stderr)
                    
                    if result.returncode != 0 or "0% packet loss" not in result.stdout:
                        overall_success = False
                        
                except Exception as e:
                    all_errors.append(str(e))
                    overall_success = False
            
            elif step_type == "command":
                command = step.get("command", parameters.get("command"))
                
                try:
                    result = subprocess.run(command.split(), capture_output=True, text=True, timeout=30)
                    
                    all_output.append(f"Step {step.get('name', 'command')}: {result.stdout}")
                    if result.stderr:
                        all_errors.append(result.stderr)
                    
                    if result.returncode != 0:
                        overall_success = False
                        
                except Exception as e:
                    all_errors.append(str(e))
                    overall_success = False
        
        execution_time = time.time() - start_time
        
        return TaskResult(
            task_id=parameters.get("task_id", self.name),
            status=TaskStatus.PASSED if overall_success else TaskStatus.FAILED,
            stdout="\n".join(all_output),
            stderr="\n".join(all_errors),
            execution_time=execution_time,
            points_earned=parameters.get("points", 10) if overall_success else 0,
            points_possible=parameters.get("points", 10)
        )

class PluginBasedGrader(NetworkGrader):
    """Extended grader that uses plugins"""
    
    def __init__(self):
        super().__init__()
        self.plugin_manager = PluginManager()
    
    async def execute_plugin_task(self, task_id: str, plugin_name: str, device_id: str, parameters: Dict[str, Any]) -> TaskResult:
        """Execute a task using a plugin"""
        device = self.devices.get(device_id)
        if not device:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.ERROR,
                stderr=f"Device {device_id} not found",
                points_possible=parameters.get("points", 10)
            )
        
        plugin = self.plugin_manager.get_plugin(plugin_name)
        if not plugin:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.ERROR,
                stderr=f"Plugin {plugin_name} not found",
                points_possible=parameters.get("points", 10)
            )
        
        # Validate parameters
        validation_errors = plugin.validate_parameters(parameters)
        if validation_errors:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.ERROR,
                stderr=f"Parameter validation failed: {', '.join(validation_errors)}",
                points_possible=parameters.get("points", 10)
            )
        
        # Add task_id to parameters
        parameters["task_id"] = task_id
        
        # Execute plugin
        return await plugin.execute(device, parameters)