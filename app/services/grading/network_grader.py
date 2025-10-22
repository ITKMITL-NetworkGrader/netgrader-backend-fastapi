"""
Network Grader - Core network grading engine

A minimal implementation that demonstrates the core concept of network grading
without complex dependencies. Uses basic SSH/paramiko and simple task execution.
"""

import logging
import time
import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum

# Set up logging
logger = logging.getLogger(__name__)

class TaskStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"

@dataclass
class Device:
    """Device representation"""
    id: str
    ip_address: str
    username: str
    password: str
    device_type: str = "linux"  # "linux" or "cisco"

@dataclass
class Task:
    """Task representation"""
    task_id: str
    task_type: str  # "ping", "ssh_command"
    execution_device: str
    parameters: Dict[str, Any]
    points: int = 10

@dataclass
class TaskResult:
    """Task result"""
    task_id: str
    status: TaskStatus
    stdout: str = ""
    stderr: str = ""
    execution_time: float = 0.0
    points_earned: int = 0
    points_possible: int = 10
    debug_info: Optional[Dict[str, Any]] = None

class NetworkGrader:
    """Network grading implementation"""
    
    def __init__(self):
        self.devices: Dict[str, Device] = {}
        self.results: List[TaskResult] = []
    
    async def add_device(self, device: Device):
        """Add a device to the grader"""
        self.devices[device.id] = device
        logger.info(f"Added device: {device.id} ({device.ip_address})")
    
    async def ping_test(self, task: Task) -> TaskResult:
        """Ping test implementation"""
        start_time = time.time()
        
        device = self.devices.get(task.execution_device)
        if not device:
            return TaskResult(
                task_id=task.task_id,
                status=TaskStatus.ERROR,
                stderr=f"Device {task.execution_device} not found",
                execution_time=time.time() - start_time
            )
        
        target_ip = task.parameters.get("target_ip")
        ping_count = task.parameters.get("ping_count", 3)
        
        logger.info(f"Executing ping from {device.id} to {target_ip}")
        
        try:
            # Use system ping command
            import subprocess
            
            if device.device_type == "linux":
                # For Linux devices, we can run ping directly or via SSH
                if device.ip_address == "localhost" or device.ip_address == "127.0.0.1":
                    # Local execution
                    cmd = ["ping", "-c", str(ping_count), target_ip]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                else:
                    # SSH execution (simplified - would need actual SSH)
                    cmd = ["ping", "-c", str(ping_count), target_ip]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            else:
                # For network devices, simulate or use actual commands
                cmd = ["ping", "-c", str(ping_count), target_ip]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            execution_time = time.time() - start_time
            
            # Analyze results
            success = result.returncode == 0 and "0% packet loss" in result.stdout
            
            return TaskResult(
                task_id=task.task_id,
                status=TaskStatus.PASSED if success else TaskStatus.FAILED,
                stdout=result.stdout,
                stderr=result.stderr,
                execution_time=execution_time,
                points_earned=task.points if success else 0,
                points_possible=task.points
            )
            
        except Exception as e:
            return TaskResult(
                task_id=task.task_id,
                status=TaskStatus.ERROR,
                stderr=str(e),
                execution_time=time.time() - start_time,
                points_earned=0,
                points_possible=task.points
            )
    
    async def ssh_command_test(self, task: Task) -> TaskResult:
        """SSH command test"""
        start_time = time.time()
        
        device = self.devices.get(task.execution_device)
        if not device:
            return TaskResult(
                task_id=task.task_id,
                status=TaskStatus.ERROR,
                stderr=f"Device {task.execution_device} not found",
                execution_time=time.time() - start_time
            )
        
        command = task.parameters.get("command", "whoami")
        
        logger.info(f"Executing SSH command on {device.id}: {command}")
        
        try:
            if device.ip_address == "localhost" or device.ip_address == "127.0.0.1":
                # Local execution for testing
                import subprocess
                result = subprocess.run(command.split(), capture_output=True, text=True, timeout=30)
                
                execution_time = time.time() - start_time
                success = result.returncode == 0
                
                return TaskResult(
                    task_id=task.task_id,
                    status=TaskStatus.PASSED if success else TaskStatus.FAILED,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    execution_time=execution_time,
                    points_earned=task.points if success else 0,
                    points_possible=task.points
                )
            else:
                # Would implement actual SSH here
                return TaskResult(
                    task_id=task.task_id,
                    status=TaskStatus.ERROR,
                    stderr="SSH not implemented in this version",
                    execution_time=time.time() - start_time
                )
                
        except Exception as e:
            return TaskResult(
                task_id=task.task_id,
                status=TaskStatus.ERROR,
                stderr=str(e),
                execution_time=time.time() - start_time,
                points_earned=0,
                points_possible=task.points
            )
    
    async def execute_task(self, task: Task) -> TaskResult:
        """Execute a task based on its type"""
        logger.info(f"Executing task {task.task_id} ({task.task_type})")
        
        if task.task_type == "ping":
            return await self.ping_test(task)
        elif task.task_type == "ssh_command":
            return await self.ssh_command_test(task)
        else:
            return TaskResult(
                task_id=task.task_id,
                status=TaskStatus.ERROR,
                stderr=f"Unknown task type: {task.task_type}",
                points_possible=task.points
            )
    
    async def run_grading_job(self, tasks: List[Task]) -> Dict[str, Any]:
        """Run a complete grading job"""
        logger.info(f"Starting grading job with {len(tasks)} tasks")
        
        self.results = []
        total_points_possible = 0
        total_points_earned = 0
        
        for task in tasks:
            result = await self.execute_task(task)
            self.results.append(result)
            
            total_points_possible += result.points_possible
            total_points_earned += result.points_earned
            
            # Log result
            status_emoji = "✅" if result.status == TaskStatus.PASSED else ("❌" if result.status == TaskStatus.FAILED else "⚠️")
            logger.info(f"{status_emoji} {task.task_id}: {result.status.value} ({result.points_earned}/{result.points_possible} pts)")
        
        success_rate = (total_points_earned / total_points_possible * 100) if total_points_possible > 0 else 0
        
        summary = {
            "total_tasks": len(tasks),
            "total_points_possible": total_points_possible,
            "total_points_earned": total_points_earned,
            "success_rate": success_rate,
            "status": "completed",
            "results": [
                {
                    "task_id": r.task_id,
                    "status": r.status.value,
                    "points_earned": r.points_earned,
                    "points_possible": r.points_possible,
                    "execution_time": r.execution_time,
                    "stdout": r.stdout,
                    "stderr": r.stderr
                }
                for r in self.results
            ]
        }
        
        logger.info(f"Grading completed: {total_points_earned}/{total_points_possible} points ({success_rate:.1f}%)")
        return summary