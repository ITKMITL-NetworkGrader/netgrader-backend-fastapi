"""
Nornir Grading Service - Nornir-based network grading implementation
"""

import logging
import os
import tempfile
import time
import yaml
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

# Nornir imports
from nornir import InitNornir
from nornir.core.inventory import Inventory
from nornir.core.task import Task, Result
from nornir_netmiko import netmiko_send_command, netmiko_send_config
from nornir_napalm.plugins.tasks import napalm_get
from nornir_utils.plugins.functions import print_result

# Import our existing models and new connection manager
from .network_grader import Device as SimpleDevice, TaskResult, TaskStatus
from app.services.connectivity.connection_manager import ConnectionManager, ConnectionMode
from app.schemas.models import ExecutionMode

logger = logging.getLogger(__name__)

class NornirGradingService:
    """
    Nornir-based grading service with connection isolation support.
    Uses ConnectionManager for isolated and stateful task execution.
    """
    
    def __init__(self):
        self.connection_manager = ConnectionManager()
        self._initialized = False
        
    async def add_device(self, device: SimpleDevice):
        """Add a device to the grader via connection manager"""
        await self.connection_manager.add_device(device)
        logger.info(f"Added device: {device.id} ({device.ip_address}) - {device.device_type}")
    
    def _convert_execution_mode(self, execution_mode: ExecutionMode) -> ConnectionMode:
        """Convert ExecutionMode to ConnectionMode"""
        mode_mapping = {
            ExecutionMode.ISOLATED: ConnectionMode.ISOLATED,
            ExecutionMode.STATEFUL: ConnectionMode.STATEFUL,
            ExecutionMode.SHARED: ConnectionMode.SHARED
        }
        return mode_mapping.get(execution_mode, ConnectionMode.ISOLATED)
        
    async def execute_ping_task(self, task_id: str, device_id: str, parameters: Dict[str, Any]) -> TaskResult:
        """Execute ping task using nornir-netmiko with connection isolation"""
        start_time = time.time()
        target_ip = parameters.get("target_ip")
        ping_count = parameters.get("ping_count", 3)
        points = parameters.get("points", 10)
        execution_mode = parameters.get("execution_mode", ExecutionMode.ISOLATED)
        session_id = parameters.get("stateful_session_id")
        connection_timeout = parameters.get("connection_timeout", 30)
        
        # Convert execution mode
        connection_mode = self._convert_execution_mode(execution_mode)
        
        try:
            # Check if this is a localhost device first
            device = self.connection_manager.devices.get(device_id)
            if device and (device.ip_address in ["localhost", "127.0.0.1"] or device.ip_address.startswith("127.")):
                # Execute ping locally using subprocess for localhost devices
                import subprocess
                ping_command = ["ping", "-c", str(ping_count), target_ip]
                
                try:
                    result = subprocess.run(ping_command, capture_output=True, text=True, timeout=30)
                    execution_time = time.time() - start_time
                    
                    # Analyze results for local ping
                    success = result.returncode == 0 and ("0% packet loss" in result.stdout or f"{ping_count} received" in result.stdout)
                    
                    return TaskResult(
                        task_id=task_id,
                        status=TaskStatus.PASSED if success else TaskStatus.FAILED,
                        stdout=result.stdout,
                        stderr=result.stderr,
                        execution_time=execution_time,
                        points_earned=points if success else 0,
                        points_possible=points
                    )
                except subprocess.TimeoutExpired:
                    return TaskResult(
                        task_id=task_id,
                        status=TaskStatus.FAILED,
                        stderr="Ping command timed out",
                        execution_time=time.time() - start_time,
                        points_earned=0,
                        points_possible=points
                    )
            
            # Use connection manager for remote devices
            async with self.connection_manager.get_connection(
                device_id=device_id, 
                connection_mode=connection_mode,
                session_id=session_id
            ) as context:
                
                # Get filtered Nornir instance for this device
                device_nr = self.connection_manager.get_filtered_nornir(context, device_id)
                
                # Get device platform to determine ping command format
                device_host = device_nr.inventory.hosts[device_id]
                device_platform = device_host.platform
                
                # Execute ping command via netmiko - choose command based on platform
                if device_platform == "ios" or "cisco" in device_platform.lower():
                    # Cisco IOS ping format
                    ping_command = f"ping {target_ip} repeat {ping_count}"
                else:
                    # Linux ping format  
                    ping_command = f"ping -c {ping_count} {target_ip}"

                result = device_nr.run(
                    task=netmiko_send_command,
                    command_string=ping_command,
                    name=f"ping_{target_ip}"
                )
                
                # Analyze results
                device_result = result[device_id]
                
                if device_result.failed:
                    success = False
                else:
                    output = device_result.result if hasattr(device_result, 'result') else str(device_result)
                    
                    # Check success based on platform
                    if device_platform == "ios" or "cisco" in device_platform.lower():
                        # Cisco IOS: Look for "Success rate is 100 percent" or "!!!!!"
                        success = ("Success rate is 100 percent" in output or 
                                  "!!!!!" in output or
                                  "5/5" in output)  # 5 out of 5 packets successful
                    else:
                        # Linux: Look for "0% packet loss" or successful ping count
                        success = ("0% packet loss" in output or 
                                  f"{ping_count} received" in output)
                
                return TaskResult(
                    task_id=task_id,
                    status=TaskStatus.PASSED if success else TaskStatus.FAILED,
                    stdout=device_result.result if hasattr(device_result, 'result') else str(device_result),
                    stderr=str(device_result.exception) if device_result.failed else "",
                    execution_time=time.time() - start_time,
                    points_earned=points if success else 0,
                    points_possible=points
                )
            
        except Exception as e:
            logger.error(f"Ping task execution failed: {e}")
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.ERROR,
                stderr=f"Ping execution failed: {str(e)}",
                execution_time=time.time() - start_time,
                points_earned=0,
                points_possible=points
            )
            
    async def execute_ssh_connectivity_test(self, task_id: str, device_id: str, parameters: Dict[str, Any]) -> TaskResult:
        """Execute SSH connectivity test with connection isolation"""
        start_time = time.time()
        target_ip = parameters.get("target_ip")
        points = parameters.get("points", 10)
        execution_mode = parameters.get("execution_mode", ExecutionMode.ISOLATED)
        session_id = parameters.get("stateful_session_id")
        connection_timeout = parameters.get("connection_timeout", 30)
        
        # Convert execution mode
        connection_mode = self._convert_execution_mode(execution_mode)
        
        try:
            # Use connection manager for isolated connection
            async with self.connection_manager.get_connection(
                device_id=device_id, 
                connection_mode=connection_mode,
                session_id=session_id
            ) as context:
                
                # Get filtered Nornir instance for this device
                device_nr = self.connection_manager.get_filtered_nornir(context, device_id)
                
                # Get device platform
                device_host = device_nr.inventory.hosts[device_id]
                device_platform = device_host.platform
                
                if device_platform == "ios" or "cisco" in device_platform.lower():
                    # For Cisco IOS: Use connect command with proper escape sequence handling
                    connect_command = f"connect {target_ip} 22"
                    
                    # Execute connect command and wait for response
                    result = device_nr.run(
                        task=netmiko_send_command,
                        command_string=connect_command,
                        expect_string=r"SSH-|Connection refused|Connection timed out|Host unreachable|%",
                        delay_factor=3,
                        max_loops=15,
                        read_timeout=10
                    )
                    
                    device_result = result[device_id]
                    
                    if device_result.failed:
                        success = False
                        output = str(device_result.exception)
                    else:
                        output = device_result.result if hasattr(device_result, 'result') else str(device_result)
                        
                        # Check if we got SSH banner (successful connection)
                        if "SSH-" in output:
                            success = True
                            
                            # Send escape sequence: Ctrl+Shift+6 then x to disconnect
                            try:
                                escape_sequence = "\x1e"  # Ctrl+Shift+6 (ASCII 30)
                                disconnect_command = f"{escape_sequence}x"
                                
                                device_nr.run(
                                    task=netmiko_send_command,
                                    command_string=disconnect_command,
                                    expect_string=r"[>#]",  # Wait for router prompt
                                    delay_factor=1,
                                    max_loops=5
                                )
                                
                                output += "\n[Connection terminated successfully]"
                                
                            except Exception as disconnect_error:
                                logger.warning(f"Disconnect sequence failed: {disconnect_error}")
                                # Still consider test successful if we got SSH banner
                                output += f"\n[Warning: Disconnect failed: {disconnect_error}]"
                                
                        else:
                            # Check for failure indicators
                            failure_indicators = [
                                "Connection refused",
                                "Connection timed out",
                                "Host unreachable", 
                                "No route to host",
                                "%"
                            ]
                            
                            success = not any(indicator in output for indicator in failure_indicators)
                            
                            # If we see "Trying" but no SSH banner or clear failure, it might be a timeout
                            if "Trying" in output and not any(indicator in output for indicator in failure_indicators):
                                if "SSH-" not in output:
                                    success = False
                                    output += "\n[Timeout: No SSH banner received]"
                        
                else:
                    # For Linux: Use netcat for SSH port testing
                    netcat_command = f"nc -zv {target_ip} 22"
                    
                    result = device_nr.run(
                        task=netmiko_send_command,
                        command_string=netcat_command,
                        name=f"ssh_port_test_{target_ip}",
                        delay_factor=2
                    )
                    
                    device_result = result[device_id]
                    
                    if device_result.failed:
                        success = False
                        output = str(device_result.exception)
                    else:
                        output = device_result.result if hasattr(device_result, 'result') else str(device_result)
                        
                        # For netcat: Look for success indicators
                        success_indicators = ["succeeded", "open", "Connection to"]
                        failure_indicators = ["refused", "failed", "timeout"]
                        
                        has_success = any(indicator in output.lower() for indicator in success_indicators)
                        has_failure = any(indicator in output.lower() for indicator in failure_indicators)
                        
                        success = has_success and not has_failure
                
                return TaskResult(
                task_id=task_id,
                status=TaskStatus.PASSED if success else TaskStatus.FAILED,
                stdout=output,
                stderr="" if success else f"SSH connectivity test failed: {output}",
                execution_time=time.time() - start_time,
                points_earned=points if success else 0,
                points_possible=points
            )
            
        except Exception as e:
            logger.error(f"SSH connectivity test execution failed: {e}")
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.ERROR,
                stderr=f"SSH connectivity test failed: {str(e)}",
                execution_time=time.time() - start_time,
                points_earned=0,
                points_possible=points
            )

    async def execute_command_task(self, task_id: str, device_id: str, parameters: Dict[str, Any]) -> TaskResult:
        """Execute command task using nornir-netmiko with connection isolation"""
        start_time = time.time()
        command = parameters.get("command")
        points = parameters.get("points", 10)
        execution_mode = parameters.get("execution_mode", ExecutionMode.ISOLATED)
        session_id = parameters.get("stateful_session_id")
        connection_timeout = parameters.get("connection_timeout", 30)
        
        # Convert execution mode
        connection_mode = self._convert_execution_mode(execution_mode)
        
        try:
            # Use connection manager for isolated connection
            async with self.connection_manager.get_connection(
                device_id=device_id, 
                connection_mode=connection_mode,
                session_id=session_id
            ) as context:
                
                # Get filtered Nornir instance for this device
                device_nr = self.connection_manager.get_filtered_nornir(context, device_id)
                
                # Execute command via netmiko
                result = device_nr.run(
                    task=netmiko_send_command,
                    command_string=command,
                    name=f"command_{command[:20]}"
                )
                
                # Analyze results
                device_result = result[device_id]
                success = not device_result.failed
                
                return TaskResult(
                    task_id=task_id,
                    status=TaskStatus.PASSED if success else TaskStatus.FAILED,
                    stdout=device_result.result if hasattr(device_result, 'result') else str(device_result),
                    stderr=str(device_result.exception) if device_result.failed else "",
                    execution_time=time.time() - start_time,
                    points_earned=points if success else 0,
                    points_possible=points
                )
            
        except Exception as e:
            logger.error(f"Command task execution failed: {e}")
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.ERROR,
                stderr=f"Command execution failed: {str(e)}",
                execution_time=time.time() - start_time,
                points_earned=0,
                points_possible=points
            )
            
    async def execute_napalm_task(self, task_id: str, device_id: str, parameters: Dict[str, Any]) -> TaskResult:
        """Execute NAPALM task using nornir-napalm with connection isolation"""
        start_time = time.time()
        operation = parameters.get("operation", "get_interfaces")
        points = parameters.get("points", 10)
        execution_mode = parameters.get("execution_mode", ExecutionMode.ISOLATED)
        session_id = parameters.get("stateful_session_id")
        connection_timeout = parameters.get("connection_timeout", 30)
        
        # Convert execution mode
        connection_mode = self._convert_execution_mode(execution_mode)
        
        try:
            # Use connection manager for isolated connection
            async with self.connection_manager.get_connection(
                device_id=device_id, 
                connection_mode=connection_mode,
                session_id=session_id
            ) as context:
                
                # Get filtered Nornir instance for this device
                device_nr = self.connection_manager.get_filtered_nornir(context, device_id)
                
                # Map operation to NAPALM getter
                getter_map = {
                    "get_interfaces": "interfaces",
                    "get_interfaces_ip": "interfaces_ip", 
                    "get_facts": "facts",
                    "get_arp_table": "arp_table",
                    "get_route_to": "route_to"
                }
                
                getter = getter_map.get(operation, operation.replace("get_", ""))
                
                # Execute NAPALM getter
                result = device_nr.run(
                    task=napalm_get,
                    getters=[getter],
                    name=f"napalm_{getter}"
                )
                
                # Analyze results
                device_result = result[device_id]
                if device_result.failed:
                    return TaskResult(
                        task_id=task_id,
                        status=TaskStatus.FAILED,
                        stderr=str(device_result.exception),
                        execution_time=time.time() - start_time,
                        points_earned=0,
                        points_possible=points
                    )
                
                napalm_data = device_result.result.get(getter, {})
                
                # Process results based on operation type
                success = True
                stdout_lines = []
                
                if getter == "interfaces":
                    interface_name = parameters.get("interface", "")
                    
                    if interface_name:
                        # Check specific interface
                        interface_data = napalm_data.get(interface_name, {})
                        is_up = interface_data.get("is_up", False)
                        is_enabled = interface_data.get("is_enabled", False)
                        
                        stdout_lines.append(f"Interface {interface_name}:")
                        stdout_lines.append(f"  Operational: {is_up}")
                        stdout_lines.append(f"  Enabled: {is_enabled}")
                        
                        success = is_up and is_enabled
                    else:
                        # List all interfaces
                        stdout_lines.append("All interfaces:")
                        for iface, data in napalm_data.items():
                            status = "UP" if data.get("is_up") else "DOWN"
                            stdout_lines.append(f"  {iface}: {status}")
                            
                elif getter == "interfaces_ip":
                    interface_name = parameters.get("interface", "")
                    expected_ip = parameters.get("expected_ip", "")
                    
                    if interface_name:
                        interface_ips = napalm_data.get(interface_name, {})
                        stdout_lines.append(f"Interface {interface_name} IP addresses:")
                        
                        for ip_addr, ip_data in interface_ips.get("ipv4", {}).items():
                            stdout_lines.append(f"  {ip_addr}/{ip_data.get('prefix_length', 'unknown')}")
                        
                        if expected_ip:
                            has_expected_ip = expected_ip in interface_ips.get("ipv4", {})
                            success = has_expected_ip
                            if not has_expected_ip:
                                stdout_lines.append(f"  Expected IP {expected_ip} not found!")
                        else:
                            success = len(interface_ips.get("ipv4", {})) > 0
                    else:
                        # List all interface IPs
                        stdout_lines.append("All interface IP addresses:")
                        for iface, data in napalm_data.items():
                            ips = list(data.get("ipv4", {}).keys())
                            ip_str = ", ".join(ips) if ips else "No IPs"
                            stdout_lines.append(f"  {iface}: {ip_str}")
                            
                else:
                    # Generic output for other getters
                    stdout_lines.append(f"NAPALM {getter} result:")
                    stdout_lines.append(str(napalm_data))
                
                return TaskResult(
                    task_id=task_id,
                    status=TaskStatus.PASSED if success else TaskStatus.FAILED,
                    stdout="\n".join(stdout_lines),
                    stderr="",
                    execution_time=time.time() - start_time,
                    points_earned=points if success else 0,
                    points_possible=points
                )
            
        except Exception as e:
            logger.error(f"NAPALM task execution failed: {e}")
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.ERROR,
                stderr=f"NAPALM execution failed: {str(e)}",
                execution_time=time.time() - start_time,
                points_earned=0,
                points_possible=points
            )
            
    async def execute_task(self, task_id: str, task_type: str, device_id: str, parameters: Dict[str, Any]) -> TaskResult:
        """Execute a task based on its type using appropriate Nornir plugin"""
        logger.info(f"Executing Nornir task {task_id} ({task_type}) on {device_id}")
        
        if task_type == "ping":
            return await self.execute_ping_task(task_id, device_id, parameters)
        elif task_type == "command":
            return await self.execute_command_task(task_id, device_id, parameters)  
        elif task_type == "napalm":
            return await self.execute_napalm_task(task_id, device_id, parameters)
        elif task_type == "ssh_test":
            return await self.execute_ssh_connectivity_test(task_id, device_id, parameters)
        elif task_type == "custom":
            return await self.execute_custom_task(task_id, device_id, parameters)
        else:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.ERROR,
                stderr=f"Unknown task type: {task_type}",
                points_possible=parameters.get("points", 10)
            )
            
    async def execute_custom_task(self, task_id: str, device_id: str, parameters: Dict[str, Any]) -> TaskResult:
        """
        Execute a custom instructor-defined task
        
        Args:
            task_id: Unique identifier for this task execution
            device_id: Target device identifier  
            parameters: Task parameters including custom_task_id
            
        Returns:
            TaskResult with execution results
        """
        start_time = time.time()
        custom_task_id = parameters.get("custom_task_id")
        points = parameters.get("points", 10)
        
        if not custom_task_id:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.ERROR,
                stderr="custom_task_id parameter is required for custom tasks",
                execution_time=time.time() - start_time,
                points_earned=0,
                points_possible=points
            )
        
        try:
            # Import CustomTaskExecutor here to avoid circular imports
            from app.services.custom_tasks.custom_task_executor import CustomTaskExecutor
            
            # Create executor if not already exists
            if not hasattr(self, '_custom_executor'):
                self._custom_executor = CustomTaskExecutor(self)
            
            # Execute custom task
            custom_result = await self._custom_executor.execute_custom_task(
                task_id=task_id,
                custom_task_id=custom_task_id,
                device_id=device_id,
                parameters=parameters
            )
            
            # Convert CustomTaskExecutionResult to TaskResult
            return TaskResult(
                task_id=task_id,
                status=custom_result.status,
                stdout=custom_result.stdout,
                stderr=custom_result.stderr,
                execution_time=custom_result.execution_time,
                points_earned=custom_result.points_earned,
                points_possible=custom_result.points_possible,
                debug_info=custom_result.debug_data
            )
            
        except Exception as e:
            logger.error(f"Custom task execution failed: {e}")
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.ERROR,
                stderr=f"Custom task execution failed: {str(e)}",
                execution_time=time.time() - start_time,
                points_earned=0,
                points_possible=points
            )
            
    async def cleanup(self):
        """Clean up connection manager and temporary files"""
        await self.connection_manager.cleanup_all()
        logger.info("Cleaned up all connections and temporary files")