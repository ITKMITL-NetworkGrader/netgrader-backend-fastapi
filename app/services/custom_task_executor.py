"""
Custom Task Executor Service - Execute YAML-defined custom instructor tasks

This service executes custom tasks defined through YAML DSL, providing
a bridge between instructor-defined tests and the Nornir execution engine.
"""

import logging
import re
import json
import time
import yaml
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass

from .custom_task_registry import (
    CustomTaskDefinition, 
    CustomTaskCommand, 
    CustomTaskValidationRule,
    CustomTaskValidationCondition,
    CustomTaskRegistry
)
from .network_grader import TaskResult, TaskStatus

logger = logging.getLogger(__name__)


@dataclass
class CustomTaskExecutionContext:
    """
    Context object containing runtime data during custom task execution
    """
    task_id: str
    device_id: str
    parameters: Dict[str, Any]
    variables: Dict[str, Any]  # Variables set during execution (register values)
    execution_results: List[Dict[str, Any]]  # Results from each command
    start_time: float
    points_possible: int


@dataclass 
class CustomTaskExecutionResult:
    """
    Result of executing a complete custom task
    """
    task_id: str
    status: TaskStatus
    points_earned: int
    points_possible: int
    execution_time: float
    command_results: List[Dict[str, Any]]
    validation_results: List[Dict[str, Any]]
    stdout: str
    stderr: str
    debug_data: Optional[Dict[str, Any]] = None


class CustomTaskValidationEngine:
    """
    Engine for validating custom task results against defined rules
    """
    
    @staticmethod
    def validate_result(result_data: Any, 
                       validation_rule: CustomTaskValidationRule) -> Dict[str, Any]:
        """
        Validate a result against a validation rule
        
        Args:
            result_data: Data to validate
            validation_rule: Rule to apply
            
        Returns:
            Dictionary with validation result
        """
        try:
            # Extract field value from result data
            field_value = CustomTaskValidationEngine._extract_field_value(
                result_data, validation_rule.field
            )
            
            # Apply validation condition
            validation_passed = CustomTaskValidationEngine._apply_condition(
                field_value, 
                validation_rule.condition, 
                validation_rule.value
            )
            
            return {
                "field": validation_rule.field,
                "condition": validation_rule.condition.value,
                "expected": validation_rule.value,
                "actual": field_value,
                "passed": validation_passed,
                "description": validation_rule.description or f"Validate {validation_rule.field}"
            }
            
        except Exception as e:
            logger.error(f"Validation error for field {validation_rule.field}: {e}")
            return {
                "field": validation_rule.field,
                "condition": validation_rule.condition.value,
                "expected": validation_rule.value,
                "actual": None,
                "passed": False,
                "error": str(e),
                "description": validation_rule.description or f"Validate {validation_rule.field}"
            }
    
    @staticmethod
    def _extract_field_value(data: Any, field_path: str) -> Any:
        """
        Extract field value from nested data using dot notation
        
        Args:
            data: Source data
            field_path: Field path (e.g., "interfaces.eth0.status" or "ssh_status")
            
        Returns:
            Extracted field value
        """
        if not field_path:
            return data
        
        # Handle simple field names
        if '.' not in field_path:
            if isinstance(data, dict):
                field_value = data.get(field_path)
                
                # If the field value is a string, clean it up (remove newlines, whitespace)
                if isinstance(field_value, str):
                    field_value = field_value.strip()
                
                return field_value
            elif hasattr(data, field_path):
                return getattr(data, field_path)
            else:
                return None
        
        # Handle nested field paths like "up_interface_count.match_count"
        parts = field_path.split('.')
        current_data = data
        
        for part in parts:
            if isinstance(current_data, dict):
                current_data = current_data.get(part)
            elif isinstance(current_data, list) and part.isdigit():
                index = int(part)
                current_data = current_data[index] if 0 <= index < len(current_data) else None
            elif hasattr(current_data, part):
                current_data = getattr(current_data, part)
            else:
                return None
            
            if current_data is None:
                break
        
        # Clean up string values
        if isinstance(current_data, str):
            current_data = current_data.strip()
        
        return current_data
    
    @staticmethod
    def _apply_condition(actual: Any, 
                        condition: CustomTaskValidationCondition, 
                        expected: Any) -> bool:
        """
        Apply validation condition to actual and expected values
        
        Args:
            actual: Actual value from execution
            condition: Validation condition to apply
            expected: Expected value
            
        Returns:
            True if validation passes, False otherwise
        """
        try:
            if condition == CustomTaskValidationCondition.EQUALS:
                return actual == expected
            
            elif condition == CustomTaskValidationCondition.CONTAINS:
                if isinstance(actual, str):
                    return str(expected) in actual
                elif isinstance(actual, (list, dict)):
                    return expected in actual
                return False
            
            elif condition == CustomTaskValidationCondition.GREATER_THAN:
                try:
                    return float(actual) > float(expected)
                except (ValueError, TypeError):
                    return False
            
            elif condition == CustomTaskValidationCondition.LESS_THAN:
                try:
                    return float(actual) < float(expected)
                except (ValueError, TypeError):
                    return False
            
            elif condition == CustomTaskValidationCondition.REGEX:
                if not isinstance(actual, str):
                    actual = str(actual)
                return bool(re.search(str(expected), actual))
            
            elif condition == CustomTaskValidationCondition.EXISTS:
                return actual is not None and actual != ""
            
            else:
                logger.warning(f"Unsupported validation condition: {condition}")
                return False
                
        except Exception as e:
            logger.error(f"Error applying condition {condition}: {e}")
            return False


class CustomTaskExecutor:
    """
    Executor for custom instructor tasks defined through YAML DSL
    
    Provides execution engine that processes custom task definitions,
    executes commands through appropriate Nornir methods, and validates results.
    """
    
    def __init__(self, nornir_grading_service):
        """
        Initialize the custom task executor
        
        Args:
            nornir_grading_service: Instance of NornirGradingService for command execution
        """
        from app.core.config import config
        
        self.nornir_service = nornir_grading_service
        self.registry = CustomTaskRegistry(config.CUSTOM_TASK_REGISTRY_DIR)
        self.validation_engine = CustomTaskValidationEngine()
        
    async def execute_custom_task(self, 
                                task_id: str,
                                custom_task_id: str,
                                device_id: str,
                                parameters: Dict[str, Any]) -> CustomTaskExecutionResult:
        """
        Execute a custom task defined through YAML DSL
        
        Args:
            task_id: Unique identifier for this execution
            custom_task_id: ID of the custom task definition to execute
            device_id: Target device identifier
            parameters: Runtime parameters for the task
            
        Returns:
            CustomTaskExecutionResult with execution results
        """
        start_time = time.time()
        
        try:
            # Retrieve custom task definition
            task_definition = self.registry.get_custom_task(custom_task_id)
            if not task_definition:
                raise ValueError(f"Custom task not found: {custom_task_id}")
            
            # Validate parameters before execution
            param_errors = self.registry.validate_parameters(custom_task_id, parameters)
            if param_errors:
                raise ValueError(f"Parameter validation failed: {'; '.join(param_errors)}")
            
            logger.info(f"Executing custom task: {task_definition.task_name} on device: {device_id}")
            
            # Create execution context
            context = CustomTaskExecutionContext(
                task_id=task_id,
                device_id=device_id,
                parameters=parameters,
                variables={},
                execution_results=[],
                start_time=start_time,
                points_possible=task_definition.points
            )
            
            # Execute each command in sequence
            command_results = []
            for i, command in enumerate(task_definition.commands):
                try:
                    logger.debug(f"Executing command {i+1}/{len(task_definition.commands)}: {command.name}")
                    
                    command_result = await self._execute_command(
                        command, context, task_definition.connection_type
                    )
                    command_results.append(command_result)
                    
                    # Store result in variables if register is specified
                    if command.register:
                        # Store the actual result, not the full command result structure
                        if command_result.get("success", False):
                            actual_result = command_result.get("result", command_result.get("stdout", ""))
                            context.variables[command.register] = actual_result
                        else:
                            context.variables[command.register] = command_result.get("stderr", "")
                    
                except Exception as e:
                    error_result = {
                        "command_name": command.name,
                        "command_index": i,
                        "success": False,
                        "error": str(e),
                        "stdout": "",
                        "stderr": str(e)
                    }
                    command_results.append(error_result)
                    logger.error(f"Command execution failed: {command.name} - {e}")
            
            # Validate results against validation rules
            validation_results = []
            for validation_rule in task_definition.validation_rules:
                # Determine what data to validate against
                validation_data = self._prepare_validation_data(context, validation_rule, command_results)
                
                validation_result = self.validation_engine.validate_result(
                    validation_data, validation_rule
                )
                validation_results.append(validation_result)
            
            # Calculate overall success and points
            total_validations = len(validation_results)
            passed_validations = sum(1 for v in validation_results if v["passed"])
            
            if total_validations == 0:
                # If no validations, consider success based on command execution
                success_rate = sum(1 for c in command_results if c.get("success", False)) / len(command_results)
                overall_success = success_rate > 0.5  # At least half commands succeeded
                points_earned = int(task_definition.points * success_rate)
            else:
                # Base success on validation results
                success_rate = passed_validations / total_validations
                overall_success = success_rate == 1.0  # All validations must pass
                points_earned = int(task_definition.points * success_rate)
            
            # Prepare output strings with debug information
            stdout_lines = [f"Custom Task: {task_definition.task_name}"]
            stdout_lines.append(f"Description: {task_definition.description}")
            stdout_lines.append(f"Commands executed: {len(command_results)}")
            stdout_lines.append(f"Validations: {passed_validations}/{total_validations} passed")
            
            # Add debug information if configured
            if task_definition.debug_config:
                debug_config = task_definition.debug_config
                stdout_lines.append("")
                stdout_lines.append("=== DEBUG INFORMATION ===")
                
                if debug_config.show_parameter_substitution:
                    stdout_lines.append(f"📝 PARAMETERS RECEIVED:")
                    for param_name, param_value in parameters.items():
                        stdout_lines.append(f"  • {param_name} = '{param_value}'")
                    stdout_lines.append("")
                
                if debug_config.show_registered_variables:
                    stdout_lines.append(f"📦 REGISTERED VARIABLES:")
                    for var_name, var_value in context.variables.items():
                        # Truncate long values for readability
                        display_value = str(var_value)
                        if len(display_value) > 100:
                            display_value = display_value[:100] + "..."
                        stdout_lines.append(f"  • {var_name} = '{display_value}'")
                    stdout_lines.append("")
                
                if debug_config.show_command_results:
                    stdout_lines.append(f"🔧 COMMAND RESULTS:")
                    for i, cmd_result in enumerate(command_results):
                        cmd_name = cmd_result.get("command_name", f"Command_{i}")
                        success = cmd_result.get("success", False)
                        result = cmd_result.get("result", cmd_result.get("stdout", ""))
                        
                        # Truncate long results
                        display_result = str(result)
                        if len(display_result) > 150:
                            display_result = display_result[:150] + "..."
                        
                        status_icon = "✅" if success else "❌"
                        stdout_lines.append(f"  {status_icon} {cmd_name}: '{display_result}'")
                    stdout_lines.append("")
                
                if debug_config.show_validation_details:
                    stdout_lines.append(f"🔍 VALIDATION DETAILS:")
                    for i, val_result in enumerate(validation_results):
                        field = val_result.get("field", f"validation_{i}")
                        passed = val_result.get("passed", False)
                        expected = val_result.get("expected")
                        actual = val_result.get("actual")
                        
                        status_icon = "✅" if passed else "❌"
                        stdout_lines.append(f"  {status_icon} {field}: expected='{expected}', got='{actual}'")
                    stdout_lines.append("")
                
                if debug_config.custom_debug_points:
                    stdout_lines.append(f"🎯 CUSTOM DEBUG POINTS:")
                    for debug_point in debug_config.custom_debug_points:
                        if debug_point in context.variables:
                            value = context.variables[debug_point]
                            stdout_lines.append(f"  • {debug_point} = '{value}'")
                        else:
                            stdout_lines.append(f"  • {debug_point} = NOT FOUND")
                    stdout_lines.append("")
                
                stdout_lines.append("=== END DEBUG ===")
                stdout_lines.append("")
            
            stderr_lines = []
            for result in command_results:
                if not result.get("success", True):
                    stderr_lines.append(f"Command '{result['command_name']}' failed: {result.get('error', 'Unknown error')}")
            
            for result in validation_results:
                if not result["passed"]:
                    stderr_lines.append(f"Validation failed: {result['description']} (expected: {result['expected']}, got: {result['actual']})")
            
            execution_time = time.time() - start_time
            
            # Prepare structured debug data for API callbacks
            debug_data = None
            if task_definition.debug_config:
                debug_config = task_definition.debug_config
                debug_data = {
                    "enabled": True,
                    "parameters_received": parameters if debug_config.show_parameter_substitution else None,
                    "registered_variables": dict(context.variables) if debug_config.show_registered_variables else None,
                    "command_results": [
                        {
                            "name": cmd.get("command_name"),
                            "action": cmd.get("command_action"),
                            "success": cmd.get("success"),
                            "result": cmd.get("result"),
                            "stdout": cmd.get("stdout"),
                            "stderr": cmd.get("stderr")
                        } for cmd in command_results
                    ] if debug_config.show_command_results else None,
                    "validation_details": validation_results if debug_config.show_validation_details else None,
                    "custom_debug_points": {
                        point: context.variables.get(point) for point in debug_config.custom_debug_points or []
                    } if debug_config.custom_debug_points else None
                }
            
            return CustomTaskExecutionResult(
                task_id=task_id,
                status=TaskStatus.PASSED if overall_success else TaskStatus.FAILED,
                points_earned=points_earned,
                points_possible=task_definition.points,
                execution_time=execution_time,
                command_results=command_results,
                validation_results=validation_results,
                stdout="\n".join(stdout_lines),
                stderr="\n".join(stderr_lines) if stderr_lines else "",
                debug_data=debug_data
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Custom task execution failed: {e}")
            
            return CustomTaskExecutionResult(
                task_id=task_id,
                status=TaskStatus.ERROR,
                points_earned=0,
                points_possible=10,  # Default points
                execution_time=execution_time,
                command_results=[],
                validation_results=[],
                stdout="",
                stderr=f"Custom task execution failed: {str(e)}"
            )
    
    async def _execute_command(self, 
                             command: CustomTaskCommand,
                             context: CustomTaskExecutionContext,
                             connection_type) -> Dict[str, Any]:
        """
        Execute a single command within a custom task
        
        Args:
            command: Command to execute
            context: Execution context
            connection_type: Type of connection to use
            
        Returns:
            Dictionary with command execution result
        """
        try:
            # Resolve parameters with context variables and task parameters
            resolved_params = self._resolve_parameters(command.parameters, context)
            # Execute based on action type
            if command.action == "napalm_get":
                result = await self._execute_napalm_command(command, context, resolved_params)
            elif command.action == "netmiko_send_command":
                result = await self._execute_netmiko_command(command, context, resolved_params)
            elif command.action == "ping":
                result = await self._execute_ping_command(command, context, resolved_params)
            elif command.action == "parse_output":
                result = self._execute_parse_command(command, context, resolved_params)
            elif command.action == "custom_script":
                result = await self._execute_custom_script(command, context, resolved_params)
            else:
                raise ValueError(f"Unsupported command action: {command.action}")
            
            return {
                "command_name": command.name,
                "command_action": command.action,
                "success": True,
                "result": result,
                "stdout": str(result) if result else "",
                "stderr": ""
            }
            
        except Exception as e:
            return {
                "command_name": command.name,
                "command_action": command.action,
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": str(e)
            }
    
    async def _execute_napalm_command(self, 
                                    command: CustomTaskCommand,
                                    context: CustomTaskExecutionContext,
                                    resolved_params: Dict[str, Any]) -> Any:
        """Execute NAPALM command through Nornir service"""
        napalm_params = {
            "operation": resolved_params.get("getter", "get_interfaces"),
            "points": resolved_params.get("points", context.points_possible)
        }
        
        # Add any additional parameters
        for key, value in resolved_params.items():
            if key not in ["getter", "points"]:
                napalm_params[key] = value
        
        nornir_result = await self.nornir_service.execute_napalm_task(
            task_id=f"{context.task_id}_{command.name}",
            device_id=context.device_id,
            parameters=napalm_params
        )
        
        # Extract the actual data from Nornir result
        if nornir_result.status == TaskStatus.PASSED:
            # Parse JSON output if available
            try:
                return json.loads(nornir_result.stdout)
            except (json.JSONDecodeError, AttributeError):
                return nornir_result.stdout
        else:
            raise Exception(f"NAPALM command failed: {nornir_result.stderr}")
    
    async def _execute_netmiko_command(self, 
                                     command: CustomTaskCommand,
                                     context: CustomTaskExecutionContext,
                                     resolved_params: Dict[str, Any]) -> str:
        """Execute Netmiko command through Nornir service"""
        netmiko_params = {
            "command": resolved_params.get("command", ""),
            "points": resolved_params.get("points", context.points_possible)
        }
        
        nornir_result = await self.nornir_service.execute_command_task(
            task_id=f"{context.task_id}_{command.name}",
            device_id=context.device_id,
            parameters=netmiko_params
        )
        
        if nornir_result.status == TaskStatus.PASSED:
            return nornir_result.stdout
        else:
            raise Exception(f"Netmiko command failed: {nornir_result.stderr}")
    
    async def _execute_ping_command(self, 
                                  command: CustomTaskCommand,
                                  context: CustomTaskExecutionContext,
                                  resolved_params: Dict[str, Any]) -> str:
        """Execute ping command through Nornir service"""
        ping_params = {
            "target_ip": resolved_params.get("target_ip", ""),
            "ping_count": resolved_params.get("ping_count", 3) or 3,
            "points": resolved_params.get("points", context.points_possible)
        }
        nornir_result = await self.nornir_service.execute_ping_task(
            task_id=f"{context.task_id}_{command.name}",
            device_id=context.device_id,
            parameters=ping_params
        )
        
        if nornir_result.status in [TaskStatus.PASSED, TaskStatus.FAILED]:
            return nornir_result.stdout
        else:
            raise Exception(f"Ping command failed: {nornir_result.stderr}")
    
    def _execute_parse_command(self, 
                             command: CustomTaskCommand,
                             context: CustomTaskExecutionContext,
                             resolved_params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute output parsing command"""
        input_text = resolved_params.get("input", "")
        pattern = resolved_params.get("pattern", "")
        
        if not pattern:
            return {"input": input_text, "parsed": input_text}
        
        try:
            # Apply regex pattern
            matches = re.findall(pattern, input_text, re.MULTILINE | re.IGNORECASE)
            
            # Return structured result
            return {
                "input": input_text,
                "pattern": pattern,
                "matches": matches,
                "match_count": len(matches),
                "first_match": matches[0] if matches else None
            }
            
        except re.error as e:
            raise Exception(f"Invalid regex pattern '{pattern}': {e}")
    
    async def _execute_custom_script(self, 
                                   command: CustomTaskCommand,
                                   context: CustomTaskExecutionContext,
                                   resolved_params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute custom script command (placeholder for future extension)"""
        # This is a placeholder for future custom scripting capability
        # For now, return a simple success result
        return {
            "message": "Custom script execution not yet implemented",
            "command": command.name,
            "parameters": resolved_params
        }
    
    def _resolve_parameters(self, 
                          parameters: Dict[str, Any],
                          context: CustomTaskExecutionContext) -> Dict[str, Any]:
        """
        Resolve parameters using context variables and task parameters
        
        Args:
            parameters: Raw parameters from command definition
            context: Execution context with variables
            
        Returns:
            Resolved parameters with substituted values
        """
        resolved = {}
        for key, value in parameters.items():
            if isinstance(value, str):
                # Simple variable substitution using {{variable}} syntax
                resolved_value = value
                # Replace context variables
                for var_name, var_value in context.variables.items():
                    placeholder = f"{{{{{var_name}}}}}"
                    if placeholder in resolved_value:
                        resolved_value = resolved_value.replace(placeholder, str(var_value))
                
                # Replace task parameters
                for param_name, param_value in context.parameters.items():
                    placeholder = f"{{{{{param_name}}}}}"
                    if placeholder in resolved_value:
                        resolved_value = resolved_value.replace(placeholder, str(param_value))
                
                # Remove any remaining unresolved placeholders
                if re.search(r'\{\{[^}]+\}\}', resolved_value):
                    #if matched, it will not updated resolved value in resolved[key].
                    continue
                resolved[key] = resolved_value
            else:
                resolved[key] = value
        
        return resolved
    
    def _prepare_validation_data(self, 
                               context: CustomTaskExecutionContext,
                               validation_rule: CustomTaskValidationRule,
                               command_results: List[Dict[str, Any]]) -> Any:
        """
        Prepare data for validation based on the validation rule
        
        Args:
            context: Execution context
            validation_rule: Validation rule being applied
            command_results: Results from all executed commands
            
        Returns:
            Data to validate against
        """
        field_path = validation_rule.field
        
        # Create a combined data structure with all variables and command results
        validation_data = {}
        
        # Add context variables (results stored with register names)
        validation_data.update(context.variables)
        
        # Add command results by name for direct access
        for cmd_result in command_results:
            cmd_name = cmd_result.get("command_name", "")
            if cmd_name:
                validation_data[cmd_name] = cmd_result
        
        # Special handling for common field patterns
        if "." in field_path:
            # Handle dot notation like "ssh_status.result" or "up_interface_count.match_count"
            parts = field_path.split(".")
            base_field = parts[0]
            
            # Look for the base field in variables first (registered results)
            if base_field in context.variables:
                return context.variables
            
            # Then look in command results
            for cmd_result in command_results:
                if cmd_result.get("command_name") == base_field:
                    return validation_data
        else:
            # Simple field name - look in variables first
            if field_path in context.variables:
                return context.variables
            
            # Then look for command with matching name
            for cmd_result in command_results:
                if cmd_result.get("command_name") == field_path:
                    return validation_data
        
        # Default to all available data
        return validation_data