"""
Nornir Grading Service - Nornir-based network grading implementation
"""

import asyncio
import ipaddress
import json
import logging
from contextlib import asynccontextmanager
from functools import partial
import os
import tempfile
import time
import yaml
from datetime import datetime
from typing import Dict, Any, List, Optional


def validate_target_ip(ip: str) -> str:
    """Validate and normalize an IP address or hostname/FQDN. Raises ValueError if invalid."""
    if not ip or not isinstance(ip, str):
        raise ValueError(f"Invalid target: {ip}")
    # Try numeric IP first
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        pass
    # Accept hostnames and FQDNs (letters, digits, hyphens, dots)
    hostname_re = re.compile(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$')
    if hostname_re.match(ip):
        return ip
    raise ValueError(f"Invalid IP address or hostname: {ip}")
from dataclasses import dataclass
from pathlib import Path
import re
from ntc_templates.parse import parse_output

# Nornir imports
from nornir import InitNornir
from nornir.core.inventory import Inventory
from nornir.core.task import Task, Result
from nornir_netmiko import netmiko_send_command, netmiko_send_config
from nornir_utils.plugins.functions import print_result

# Import our existing models and new connection manager
from app.services.connectivity.connection_manager import ConnectionManager
from app.schemas.models import ExecutionMode, Device, TaskResult, TaskStatus
from app.services.grading.exception_handler import classify_exception

logger = logging.getLogger(__name__)

_MIN_READ_TIMEOUT = 1.0
_MAX_READ_TIMEOUT = 120.0
_MIN_LAST_READ = 0.5
_MAX_LAST_READ = 30.0


class CommandExecutionError(Exception):
    """Raised when a single command fails within a shared connection."""

    def __init__(self, message: str, cause: Optional[Exception] = None, command: str = ""):
        super().__init__(message)
        self.__cause__ = cause
        self.command = command


@dataclass
class CustomTaskConnectionHandle:
    device_id: str
    device_nr: Any
    device_type: str
    device_os: str
    net_connect: Any


def _is_shell_prompt_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True

    if re.match(r'^[a-zA-Z0-9_-]+@[a-zA-Z0-9._-]+:[^\s]*[$#]\s*$', stripped):
        return True

    if re.match(r'^[a-zA-Z0-9_-]+@[a-zA-Z0-9._-]+:[^\s]*[$#]\s+\S', stripped):
        return True

    if re.match(r'^[a-zA-Z0-9_-]+[#>]\s*$', stripped):
        return True

    if re.match(r'^[a-zA-Z0-9_-]+\([a-z0-9-]+\)[#>]\s*$', stripped):
        return True

    if re.match(r'^[a-zA-Z0-9_-]+[#>]\s*\S', stripped):
        return True

    if re.match(r'^[/~][^\s]*\s*[$#]\s*$', stripped):
        return True

    if re.match(r'^[/~][^\s]*\s*[$#]\s+\S', stripped):
        return True

    return False

def netmiko_send_command_timing(task: Task, command_string: str, last_read: float = 2.0, **kwargs) -> Result:
    """
    Execute send_command_timing using the underlying Netmiko connection.
    Useful for Telnet devices or commands where prompt detection is difficult.
    """
    # Get the Netmiko connection object
    net_connect = task.host.get_connection("netmiko", task.nornir.config)
    
    # Execute the command using timing
    # Filter out kwargs that send_command_timing doesn't accept if necessary, 
    # but netmiko usually handles kwargs well.
    output = net_connect.send_command_timing(command_string, last_read=last_read, **kwargs)
    
    return Result(host=task.host, result=output)

class NornirGradingService:
    """
    Nornir-based grading service with connection isolation support.
    Uses ConnectionManager for isolated and stateful task execution.
    """
    
    def __init__(self):
        self.connection_manager = ConnectionManager()
        self._initialized = False
        self._custom_task_registry = None  # Set externally after initialization
        # self._ensure_textfsm_templates()
    
    async def _run_nornir_task(self, device_nr, task, **kwargs):
        """Run a synchronous Nornir task without blocking the event loop.
        
        Nornir's run() is synchronous and uses threads internally. Running it
        directly in async code blocks the event loop. This wrapper uses
        run_in_executor to run it in the default ThreadPoolExecutor.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,  # Use default ThreadPoolExecutor
            partial(device_nr.run, task=task, **kwargs)
        )
    
    def set_custom_task_registry(self, registry):
        """Set the custom task registry for custom task execution.
        
        Args:
            registry: Pre-initialized CustomTaskRegistry instance
        """
        self._custom_task_registry = registry

    @staticmethod
    def _clean_telnet_output(output: str, device_type: str, device_os: str) -> str:
        """Remove prompt noise and control sequences from telnet command output."""
        if not isinstance(output, str):
            return output

        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\].*?(?:\x07|\x1B\\))')
        cleaned = ansi_escape.sub('', output)

        osc_remnants = re.compile(r'\d+;[^\s]+@[^\s]+:[^\n]*')
        cleaned = osc_remnants.sub('', cleaned)

        control_chars = re.compile(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]')
        cleaned = control_chars.sub('', cleaned)

        lines = [line for line in cleaned.splitlines() if not _is_shell_prompt_line(line)]
        return "\n".join(lines).strip()

    def _post_command_processing(
        self,
        handle: CustomTaskConnectionHandle,
        output: str,
    ) -> str:
        """Apply post-processing to command output: clean telnet + detect prompt.

        This reduces duplication in run_single_command and run_config_command.
        """
        # Clean telnet output if needed
        if isinstance(output, str) and handle.device_type in ("generic_termserver_telnet", "generic_telnet"):
            output = self._clean_telnet_output(output, handle.device_type, handle.device_os)

        return output

    @asynccontextmanager
    async def custom_task_connection(self, device_id: str, job_id: str = ""):
        """Create a shared connection handle for custom tasks across template executions."""
        shared_session_id = f"shared_{job_id}_{device_id}" if job_id else f"shared_{device_id}"
        async with self.connection_manager.get_connection(
            device_id=device_id,
            connection_mode=ExecutionMode.SHARED,
            session_id=shared_session_id,
        ) as conn_ctx:
            device_nr = self.connection_manager.get_filtered_nornir(conn_ctx, device_id)
            host = device_nr.inventory.hosts[device_id]
            netmiko_options = host.connection_options.get("netmiko")
            device_type = (
                netmiko_options.extras.get("device_type", "")
                if netmiko_options and netmiko_options.extras
                else ""
            )
            device_os = (host.data.get("device_os") if hasattr(host, "data") else None) or ""
            net_connect = host.get_connection("netmiko", device_nr.config)

            yield CustomTaskConnectionHandle(
                device_id=device_id,
                device_nr=device_nr,
                device_type=device_type,
                device_os=device_os,
                net_connect=net_connect,
            )

    async def run_single_command(
        self,
        handle: CustomTaskConnectionHandle,
        command: str,
        read_timeout: float = 30.0,
        last_read: Optional[float] = None,
    ) -> str:
        """Run one command through an existing custom-task shared connection."""
        try:
            read_timeout = float(read_timeout if read_timeout is not None else 30.0)
        except (TypeError, ValueError) as exc:
            raise ValueError("read_timeout must be a number") from exc

        if not (_MIN_READ_TIMEOUT <= read_timeout <= _MAX_READ_TIMEOUT):
            raise ValueError(
                f"read_timeout must be between {_MIN_READ_TIMEOUT} and {_MAX_READ_TIMEOUT} seconds"
            )

        if last_read is not None:
            try:
                last_read = float(last_read)
            except (TypeError, ValueError) as exc:
                raise ValueError("last_read must be a number") from exc

            if not (_MIN_LAST_READ <= last_read <= _MAX_LAST_READ):
                raise ValueError(
                    f"last_read must be between {_MIN_LAST_READ} and {_MAX_LAST_READ} seconds"
                )

        def _send_command() -> str:
            use_timing = last_read is not None or handle.device_type == "generic_termserver_telnet"
            if use_timing:
                timing_last_read = last_read if last_read is not None else 2.0
                output = handle.net_connect.send_command_timing(
                    command,
                    last_read=timing_last_read,
                    read_timeout=read_timeout,
                )
            else:
                output = handle.net_connect.send_command(command, read_timeout=read_timeout)
            return output

        try:
            output = await asyncio.to_thread(_send_command)
        except Exception as exc:
            raise CommandExecutionError(
                f"Command '{command}' failed",
                cause=exc,
                command=command,
            )

        return self._post_command_processing(handle, output)

    async def run_config_command(
        self,
        handle: CustomTaskConnectionHandle,
        commands: List[str],
        read_timeout: float = 60.0,
    ) -> str:
        try:
            read_timeout = float(read_timeout if read_timeout is not None else 60.0)
        except (TypeError, ValueError) as exc:
            raise ValueError("read_timeout must be a number") from exc

        def _send_config() -> str:
            # Use Netmiko's send_config_set - handles config mode automatically
            output = handle.net_connect.send_config_set(
                commands,
                read_timeout=read_timeout,
            )
            return output

        try:
            output = await asyncio.to_thread(_send_config)
        except Exception as exc:
            raise CommandExecutionError(
                f"Config commands failed",
                cause=exc,
                command=str(commands),
            )

        return self._post_command_processing(handle, output)

    async def add_device(self, device: Device):
        """Add a device to the grader via connection manager"""
        await self.connection_manager.add_device(device)
        logger.info(f"Added device: {device.id} ({device.ip_address}) - {device.platform}")
    

        
    async def execute_ping_task(self, task_id: str, device_id: str, parameters: Dict[str, Any]) -> TaskResult:
        """Execute ping task using nornir-netmiko with connection isolation"""
        start_time = time.time()
        target_ip = parameters.get("target_ip")
        ping_count = parameters.get("ping_count", 3)
        points = parameters.get("points", 10.0)
        try:
            target_ip = validate_target_ip(target_ip)
        except (ValueError, TypeError):
            return TaskResult(
                task_id=task_id, status=TaskStatus.ERROR,
                stderr="Invalid target_ip",
                points_earned=0, points_possible=points,
            )

        try:
            # Check if this is a localhost device first
            device = self.connection_manager.devices.get(device_id)
            if device and (device.ip_address in ["localhost", "127.0.0.1"] or device.ip_address.startswith("127.")):
                # Execute ping locally using subprocess for localhost devices
                import subprocess
                ping_command = ["ping", "-c", str(ping_count), target_ip]

                try:
                    # Wrap blocking subprocess with asyncio.to_thread for non-blocking execution
                    result = await asyncio.get_running_loop().run_in_executor(
                        None,
                        lambda: subprocess.run(ping_command, capture_output=True, text=True, timeout=30)
                    )
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
            
            # Use connection manager — shared per device so all tasks reuse one SSH session
            job_id = parameters.get("job_id", "")
            async with self.connection_manager.get_connection(
                device_id=device_id,
                connection_mode=ExecutionMode.SHARED,
                session_id=f"shared_{job_id}_{device_id}" if job_id else f"shared_{device_id}",
            ) as context:

                # Get filtered Nornir instance for this device
                device_nr = self.connection_manager.get_filtered_nornir(context, device_id)

                # Get device OS to determine ping command format
                device_host = device_nr.inventory.hosts[device_id]
                device_os = device_host.data.get("device_os", "") if hasattr(device_host, 'data') else ""
                # Execute ping command via netmiko - choose command based on device OS
                if device_os == "ios" or (device_os and "cisco" in device_os.lower()):
                    # Cisco IOS ping format
                    ping_command = f"ping {target_ip} repeat {ping_count}"
                else:
                    # Linux ping format  
                    ping_command = f"ping -c {ping_count} {target_ip}"

                result = await self._run_nornir_task(
                    device_nr,
                    netmiko_send_command,
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
                    if device_os == "ios" or "cisco" in device_os.lower():
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
            error = classify_exception(e)
            logger.error(f"Ping task execution failed: {error.internal_details}")
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.ERROR,
                stderr=error.user_message,
                execution_time=time.time() - start_time,
                points_earned=0,
                points_possible=points
            )
            
    async def execute_ssh_connectivity_test(self, task_id: str, device_id: str, parameters: Dict[str, Any]) -> TaskResult:
        """Execute SSH connectivity test with connection isolation"""
        start_time = time.time()
        target_ip = parameters.get("target_ip")
        points = parameters.get("points", 10.0)
        try:
            # Use connection manager — shared per device so all tasks reuse one SSH session
            job_id = parameters.get("job_id", "")
            async with self.connection_manager.get_connection(
                device_id=device_id,
                connection_mode=ExecutionMode.SHARED,
                session_id=f"shared_{job_id}_{device_id}" if job_id else f"shared_{device_id}",
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
                    result = await self._run_nornir_task(
                        device_nr,
                        netmiko_send_command,
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
                                
                                await self._run_nornir_task(
                                    device_nr,
                                    netmiko_send_command,
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
                    
                    result = await self._run_nornir_task(
                        device_nr,
                        netmiko_send_command,
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
            error = classify_exception(e)
            logger.error(f"SSH connectivity test execution failed: {error.internal_details}")
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.ERROR,
                stderr=error.user_message,
                execution_time=time.time() - start_time,
                points_earned=0,
                points_possible=points
            )

    async def execute_command_task(self, task_id: str, device_id: str, parameters: Dict[str, Any]) -> TaskResult:
        """Execute command task using nornir-netmiko with connection isolation"""
        start_time = time.time()
        command = parameters.get("command")
        points = parameters.get("points", 10.0)
        use_textfsm = parameters.get("use_textfsm", False)
        textfsm_template = parameters.get("textfsm_template")
        last_read = parameters.get("last_read")  # New parameter for timing tasks

        try:
            # Use connection manager — shared per device so all tasks reuse one SSH session
            job_id = parameters.get("job_id", "")
            async with self.connection_manager.get_connection(
                device_id=device_id,
                connection_mode=ExecutionMode.SHARED,
                session_id=f"shared_{job_id}_{device_id}" if job_id else f"shared_{device_id}",
            ) as context:

                # Get filtered Nornir instance for this device
                device_nr = self.connection_manager.get_filtered_nornir(context, device_id)

                # Execute command via netmiko
                netmiko_kwargs = {
                    "command_string": command,
                    "name": f"command_{command[:20]}",
                }
                
                # Check platform for special handling
                device_host = device_nr.inventory.hosts[device_id]
                device_type = device_host.connection_options.get("netmiko").extras.get("device_type")
                # Determine which task to run
                task_to_run = netmiko_send_command
                if last_read is not None:
                    netmiko_kwargs["last_read"] = float(last_read)
                    task_to_run = netmiko_send_command_timing
                
                # Force timing-based execution for generic_termserver_telnet if not explicitly set
                if device_type == "generic_termserver_telnet":
                    if last_read is None:
                        last_read = 2.0
                        task_to_run = netmiko_send_command_timing
                        netmiko_kwargs["last_read"] = float(last_read)

                if use_textfsm:
                    # For generic_termserver_telnet, we handle parsing manually after cleaning
                    if device_type not in ["generic_termserver_telnet"]:
                        netmiko_kwargs["use_textfsm"] = True
                if textfsm_template:
                    netmiko_kwargs["textfsm_template"] = textfsm_template

                result = await self._run_nornir_task(
                    device_nr,
                    task_to_run,
                    **netmiko_kwargs
                )
                # Analyze results
                device_result = result[device_id]
                success = not device_result.failed
                
                raw_output = None
                if hasattr(device_result, "result"):
                    # Apply cleaning for telnet-based connections
                    if isinstance(device_result.result, str) and device_type in ("generic_termserver_telnet", "generic_telnet"):
                        device_os = device_host.data.get("device_os") if hasattr(device_host, 'data') else ""
                        clean_output = self._clean_telnet_output(device_result.result, device_type, device_os)
                        parsed_data = []
                        try:
                            # Determine the actual device OS for parsing
                            # First, check if device_os is specified in the host data
                            if clean_output and (use_textfsm or textfsm_template):
                                parsed_data = parse_output(platform=device_os, command=command, data=clean_output)
                        except Exception as e:
                            logger.warning(f"Parsing failed for {device_id}: {e}")
                            
                        raw_output = parsed_data
                        # Update the result to be the clean output for consistency
                        device_result.result = clean_output
                        
                        # If we successfully parsed data, use it as the result for templates that expect structured data
                        if parsed_data:
                            device_result.result = parsed_data
                    elif isinstance(device_result.result, str):
                        raw_output = device_result.result
                    else:
                        raw_output = None
                
                command_output = device_result.result if hasattr(device_result, 'result') else str(device_result)
                structured_output = command_output if isinstance(command_output, (list, dict)) else None
                if isinstance(command_output, str):
                    stdout_text = command_output
                else:
                    try:
                        stdout_text = json.dumps(command_output, indent=2, sort_keys=True)
                    except (TypeError, ValueError):
                        stdout_text = str(command_output)

                debug_info: Optional[Dict[str, Any]] = None
                if structured_output is not None or raw_output is not None:
                    debug_info = {
                        "structured_output": structured_output,
                        "raw_output": raw_output,
                    }

                return TaskResult(
                    task_id=task_id,
                    status=TaskStatus.PASSED if success else TaskStatus.FAILED,
                    stdout=stdout_text,
                    stderr=str(device_result.exception) if device_result.failed else "",
                    execution_time=time.time() - start_time,
                    points_earned=points if success else 0,
                    points_possible=points,
                    debug_info=debug_info
                )
            
        except Exception as e:
            error = classify_exception(e)
            logger.error(f"Command task execution failed: {error.internal_details}")
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.ERROR,
                stderr=error.user_message,
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
        elif task_type == "ssh_test":
            return await self.execute_ssh_connectivity_test(task_id, device_id, parameters)
        elif task_type == "custom":
            return await self.execute_custom_task(task_id, device_id, parameters)
        else:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.ERROR,
                stderr=f"Unknown task type: {task_type}",
                points_possible=parameters.get("points", 10.0)
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
        points = parameters.get("points", 10.0)
        
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
                self._custom_executor = CustomTaskExecutor(self, registry=self._custom_task_registry)
            
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
            error = classify_exception(e)
            logger.error(f"Custom task execution failed: {error.internal_details}")
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.ERROR,
                stderr=error.user_message,
                execution_time=time.time() - start_time,
                points_earned=0,
                points_possible=points
            )
            
    async def cleanup(self):
        """Clean up connection manager and temporary files"""
        await self.connection_manager.cleanup_all()
        logger.info("Cleaned up all connections and temporary files")
