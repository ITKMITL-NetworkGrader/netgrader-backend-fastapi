"""
Custom Task Executor Service - Execute YAML-defined custom instructor tasks

This service executes custom tasks defined through YAML DSL, providing
a bridge between instructor-defined tests and the Nornir execution engine.
"""

import io
import logging
import re
import json
import time
import yaml
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field, replace
from ntc_templates.parse import parse_output as ntc_parse_output

try:
    import textfsm
except ImportError:  # pragma: no cover - optional dependency in some environments
    textfsm = None
from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment

from .custom_task_registry import (
    CustomTaskDefinition, 
    CustomTaskCommand, 
    CustomTaskValidationRule,
    CustomTaskValidationCondition,
    CustomTaskRegistry
)
from app.schemas.models import TaskStatus

logger = logging.getLogger(__name__)


_jinja_env = SandboxedEnvironment(
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)

_SIMPLE_TEMPLATE_PATTERN = re.compile(r"^\s*\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}\s*$")


@dataclass
class CustomTaskExecutionContext:
    """
    Context object containing runtime data during custom task execution
    """
    task_id: str
    device_id: str
    parameters: Dict[str, Any]
    variables: Dict[str, Any]  # Variables set during execution (register values)
    start_time: float
    points_possible: float
    _conn_handle: Any = None
    _raw_metas: Dict[int, Any] = field(default_factory=dict)  # Raw parser metadata keyed by command index


@dataclass 
class CustomTaskExecutionResult:
    """
    Result of executing a complete custom task
    """
    task_id: str
    status: TaskStatus
    points_earned: float
    points_possible: float
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
                # Normalize both values for consistent comparison
                # Handle boolean/string mismatches (e.g., True vs "True")
                if isinstance(actual, bool) or isinstance(expected, bool):
                    # Normalize both to lowercase strings for boolean comparison
                    actual_str = str(actual).lower()
                    expected_str = str(expected).lower()
                    return actual_str == expected_str
                if isinstance(actual, (int, float)):
                    # Convert both to strings for numeric comparison
                    actual = str(actual)
                return actual == expected
            
            elif condition == CustomTaskValidationCondition.NOT_EQUALS:
                # Handle boolean/string mismatches (e.g., True vs "True")
                if isinstance(actual, bool) or isinstance(expected, bool):
                    actual_str = str(actual).lower()
                    expected_str = str(expected).lower()
                    return actual_str != expected_str
                return actual != expected
            
            elif condition == CustomTaskValidationCondition.CONTAINS:
                if isinstance(actual, str):
                    return str(expected) in actual
                elif isinstance(actual, (list, dict)):
                    return expected in actual
                elif isinstance(actual, (int, float)):
                    # Convert both to strings for numeric comparison
                    return str(expected) == str(actual)
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
                if isinstance(expected, bool):
                    return (actual is not None and actual != "") == expected
                elif isinstance(expected, str):
                    expected_lower = expected.lower()
                    if expected_lower in ["true", "yes", "1"]:
                        return actual is not None and actual != ""
                    elif expected_lower in ["false", "no", "0"]:
                        return actual is None or actual == ""
                    else:
                        logger.warning(f"Invalid expected value for EXISTS condition: {expected}")
                        return False
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
    
    def __init__(self, nornir_grading_service, registry: CustomTaskRegistry = None):
        """
        Initialize the custom task executor
        
        Args:
            nornir_grading_service: Instance of NornirGradingService for command execution
            registry: Pre-initialized CustomTaskRegistry instance (should be initialized with MinIO)
        """
        self.nornir_service = nornir_grading_service
        self.registry = registry
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
            
            # Prepare parameters: convert to proper types and validate in one pass
            typed_parameters, param_errors = self.registry.prepare_parameters(custom_task_id, parameters)
            if param_errors:
                raise ValueError(f"Parameter validation failed: {'; '.join(param_errors)}")
            
            logger.info(f"Executing custom task: {task_definition.task_name} on device: {device_id}")
            
            # Create execution context
            context = CustomTaskExecutionContext(
                task_id=task_id,
                device_id=device_id,
                parameters=typed_parameters,
                variables={},
                start_time=start_time,
                points_possible=parameters.get("points", task_definition.points)
            )

            async def execute_command_loop() -> List[Dict[str, Any]]:
                loop_results: List[Dict[str, Any]] = []
                for i, command in enumerate(task_definition.commands):
                    try:
                        logger.debug(f"Executing command {i+1}/{len(task_definition.commands)}: {command.name}")

                        command_result = await self._execute_command(
                            command, context,
                            command_index=i
                        )
                        loop_results.append(command_result)

                        # Store result in variables if register is specified
                        if command.register:
                            # Store the actual result, not the full command result structure
                            if command_result.get("success", False):
                                actual_result = command_result.get("result", command_result.get("stdout", ""))
                                if command.register_as == "raw":
                                    if i in context._raw_metas:
                                        actual_result = context._raw_metas[i]
                                    else:
                                        raise Exception(
                                            f"Command '{command.name}': register_as='raw' but no raw metadata available "
                                            f"for action '{command.action}'. Only 'parse_output' and 'netmiko_send_command' "
                                            f"produce raw metadata."
                                        )
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
                        loop_results.append(error_result)
                        logger.error(f"Command execution failed: {command.name} - {e}")

                return loop_results
            
            # Execute each command in sequence
            requires_network_connection = any(
                cmd.action == "netmiko_send_command" for cmd in task_definition.commands
            )

            if requires_network_connection:
                async with self.nornir_service.custom_task_connection(device_id) as handle:
                    context._conn_handle = handle
                    command_results = await execute_command_loop()
            else:
                command_results = await execute_command_loop()
            
            # Validate results against validation rules
            validation_results = []
            for validation_rule in task_definition.validation_rules:
                resolved_validation_rule = self._resolve_validation_rule(validation_rule, context)
                # Determine what data to validate against
                validation_data = self._prepare_validation_data(context, resolved_validation_rule, command_results)
                
                validation_result = self.validation_engine.validate_result(
                    validation_data, resolved_validation_rule
                )
                validation_results.append(validation_result)
            
            # Calculate overall success and points
            total_validations = len(validation_results)
            passed_validations = sum(1 for v in validation_results if v["passed"])
            
            # Use job JSON points if provided, otherwise fall back to template points
            total_points = parameters.get("points", task_definition.points)
            
            if total_validations == 0:
                # If no validations, consider success based on command execution
                success_rate = sum(1 for c in command_results if c.get("success", False)) / len(command_results)
                overall_success = success_rate > 0.5  # At least half commands succeeded
                points_earned = total_points * success_rate
            else:
                # Base success on validation results
                success_rate = passed_validations / total_validations
                overall_success = success_rate == 1.0  # All validations must pass
                points_earned = total_points * success_rate
            
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
                    stdout_lines.append(f"PARAMETERS RECEIVED:")
                    for param_name, param_value in parameters.items():
                        stdout_lines.append(f"  • {param_name} = '{param_value}'")
                    stdout_lines.append("")
                
                if debug_config.show_registered_variables:
                    stdout_lines.append(f"REGISTERED VARIABLES:")
                    for var_name, var_value in context.variables.items():
                        # Truncate long values for readability
                        display_value = str(var_value)
                        if len(display_value) > 100:
                            display_value = display_value[:100] + "..."
                        stdout_lines.append(f"  • {var_name} = '{display_value}'")
                    stdout_lines.append("")
                
                if debug_config.show_command_results:
                    stdout_lines.append(f"COMMAND RESULTS:")
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
                    stdout_lines.append(f"VALIDATION DETAILS:")
                    for i, val_result in enumerate(validation_results):
                        field = val_result.get("field", f"validation_{i}")
                        passed = val_result.get("passed", False)
                        expected = val_result.get("expected")
                        actual = val_result.get("actual")
                        
                        status_icon = "✅" if passed else "❌"
                        stdout_lines.append(f"  {status_icon} {field}: expected='{expected}', got='{actual}'")
                    stdout_lines.append("")
                
                if debug_config.custom_debug_points:
                    stdout_lines.append(f"CUSTOM DEBUG POINTS:")
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
                points_possible=parameters.get("points", task_definition.points),
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
            
            # Use job JSON points if provided, otherwise use default 10 points
            error_points = parameters.get("points", 10.0)
            
            return CustomTaskExecutionResult(
                task_id=task_id,
                status=TaskStatus.ERROR,
                points_earned=0,
                points_possible=error_points,
                execution_time=execution_time,
                command_results=[],
                validation_results=[],
                stdout="",
                stderr=f"Custom task execution failed: {str(e)}"
            )
    
    _TUPLE_RESULT_ACTIONS = {"parse_output", "netmiko_send_command"}

    async def _execute_command(self, 
                             command: CustomTaskCommand,
                             context: CustomTaskExecutionContext,
                             command_index: int = 0) -> Dict[str, Any]:
        """
        Execute a single command within a custom task
        
        Args:
            command: Command to execute
            context: Execution context
            command_index: Index of this command in the sequence
            
        Returns:
            Dictionary with command execution result
        """
        try:
            # Resolve parameters with context variables and task parameters
            resolved_params = self._resolve_parameters(command, context)
            # Execute based on action type
            if command.action == "netmiko_send_command":
                result = await self._execute_netmiko_command(command, context, resolved_params)
            elif command.action == "ping":
                result = await self._execute_ping_command(command, context, resolved_params)
            elif command.action == "parse_output":
                result = self._execute_parse_command(command, context, resolved_params)
            elif command.action == "custom_script":
                result = await self._execute_custom_script(command, context, resolved_params)
            else:
                raise ValueError(f"Unsupported command action: {command.action}")
            
            # Unpack ONLY for actions that return (flat, raw) tuples
            if command.action in self._TUPLE_RESULT_ACTIONS:
                flat_result, raw_meta = result
                if command.register_as == "raw":
                    context._raw_metas[command_index] = raw_meta
                result = flat_result

            return {
                "command_name": command.name,
                "command_action": command.action,
                "success": True,
                "result": result,
                "stdout": self._stringify_result(result),
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
    

    
    async def _execute_netmiko_command(self,
                                     command: CustomTaskCommand,
                                     context: CustomTaskExecutionContext,
                                     resolved_params: Dict[str, Any]) -> Any:
        """Execute a Netmiko command through the shared custom-task connection."""
        if context._conn_handle is None:
            raise Exception("Custom task connection handle is missing")

        command_text = resolved_params.get("command", "")
        read_timeout = resolved_params.get("read_timeout", 30.0)
        last_read = resolved_params.get("last_read")
        use_textfsm = bool(resolved_params.get("use_textfsm", False))
        textfsm_template = resolved_params.get("textfsm_template")

        output = await self.nornir_service.run_single_command(
            context._conn_handle,
            command_text,
            read_timeout=read_timeout,
            last_read=last_read,
        )

        raw_output = output if isinstance(output, str) else str(output)
        structured_output: Optional[Any] = None

        if use_textfsm or textfsm_template:
            structured_output = self._parse_textfsm_output(
                command_text=command_text,
                raw_output=raw_output,
                context=context,
                textfsm_template=textfsm_template,
                use_textfsm=use_textfsm,
            )

        flat = structured_output if structured_output is not None else raw_output
        raw = {"raw_output": raw_output, "structured_output": structured_output}
        return (flat, raw)

    def _parse_textfsm_output(
        self,
        command_text: str,
        raw_output: str,
        context: CustomTaskExecutionContext,
        textfsm_template: Optional[str],
        use_textfsm: bool,
    ) -> Optional[Any]:
        """Parse command output using TextFSM template or ntc-templates lookup."""
        if textfsm_template:
            if textfsm is None:
                logger.warning("TextFSM template was provided but textfsm package is not installed")
                return None

            try:
                template_content = textfsm_template
                try:
                    with open(textfsm_template, "r", encoding="utf-8") as template_file:
                        template_content = template_file.read()
                except OSError:
                    template_content = textfsm_template

                fsm = textfsm.TextFSM(io.StringIO(template_content))
                raw_rows = fsm.ParseText(raw_output)
                return [dict(zip(fsm.header, row)) for row in raw_rows]
            except Exception as exc:
                logger.warning("TextFSM template parsing failed for command '%s': %s", command_text, exc)
                return None

        if use_textfsm:
            device_os = ""
            if context._conn_handle is not None:
                device_os = getattr(context._conn_handle, "device_os", "") or ""

            if not device_os:
                logger.warning(
                    "use_textfsm is enabled for command '%s' but device_os is unavailable; returning raw output",
                    command_text,
                )
                return None

            try:
                return ntc_parse_output(platform=device_os, command=command_text, data=raw_output)
            except Exception as exc:
                logger.warning("ntc-templates parsing failed for command '%s': %s", command_text, exc)
                return None

        return None
    
    async def _execute_ping_command(self, 
                                  command: CustomTaskCommand,
                                  context: CustomTaskExecutionContext,
                                  resolved_params: Dict[str, Any]) -> str:
        """Execute ping command through Nornir service"""
        ping_params = {
            "target_ip": resolved_params.get("target_ip", ""),
            "ping_count": resolved_params.get("ping_count", 3) or 3,
            "points": context.points_possible  # Use context points which already has the override logic
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
                             resolved_params: Dict[str, Any]) -> Any:
        """Execute output parsing command with pluggable parsers.
        
        Returns a (flat, raw) tuple for all parser types.
        """
        input_text = resolved_params.get("input", "")
        parser_type = (resolved_params.get("parser") or "regex").lower()

        if parser_type == "regex":
            pattern = resolved_params.get("pattern", "")
            if not pattern:
                raise Exception("Regex parser requires a 'pattern' parameter")

            if not isinstance(input_text, str):
                raise Exception(
                    f"Regex parser requires string input, got {type(input_text).__name__}. "
                    "Use a Jinja parse step to convert structured data first."
                )

            try:
                matches = re.findall(pattern, input_text, re.MULTILINE | re.IGNORECASE)
            except re.error as exc:
                raise Exception(f"Invalid regex pattern '{pattern}': {exc}") from exc

            flat = {
                "matches": matches,
                "match_count": len(matches),
                "first_match": matches[0] if matches else None,
            }
            raw = {**flat, "input": input_text, "pattern": pattern}
            return (flat, raw)

        if parser_type == "textfsm":
            if textfsm is None:
                raise Exception("TextFSM parser requires the 'textfsm' package to be installed")

            template_content = resolved_params.get("template")
            if not template_content:
                raise Exception("TextFSM parser requires a 'template' parameter")

            if input_text is None:
                input_text = ""
            elif not isinstance(input_text, str):
                raise Exception(
                    f"TextFSM parser requires string input, got {type(input_text).__name__}. "
                    "Use a Jinja parse step to convert structured data first."
                )

            fsm = textfsm.TextFSM(io.StringIO(template_content))
            raw_rows = fsm.ParseText(input_text)
            structured_rows = [dict(zip(fsm.header, row)) for row in raw_rows]

            flat = structured_rows
            raw = {
                "input": input_text,
                "template_header": list(fsm.header),
                "records": structured_rows,
                "raw_matches": raw_rows,
                "match_count": len(structured_rows),
            }
            return (flat, raw)

        if parser_type == "jinja":
            template_source = (
                resolved_params.get("template")
                or resolved_params.get("pattern")
                or ""
            )
            if not template_source:
                raise Exception("Jinja parser requires a 'template' or 'pattern' parameter")

            try:
                template = _jinja_env.from_string(template_source)
                render_context = {
                    **context.parameters,
                    **context.variables,
                }
                render_context["input"] = input_text
                render_context["parameters"] = context.parameters
                render_context["variables"] = context.variables
                rendered = template.render(
                    **render_context,
                )
            except TemplateError as exc:
                raise Exception(f"Jinja parsing failed: {exc}") from exc

            structured = rendered
            if isinstance(rendered, str):
                rendered_strip = rendered.strip()
                if rendered_strip:
                    try:
                        structured = json.loads(rendered_strip)
                    except json.JSONDecodeError:
                        try:
                            structured = yaml.safe_load(rendered_strip)
                        except yaml.YAMLError:
                            structured = rendered

            flat = structured
            raw = {"input": input_text, "rendered": rendered, "data": structured}
            return (flat, raw)

        raise Exception(f"Unsupported parser type '{parser_type}' for parse_output command")
    
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
                          command: CustomTaskCommand,
                          context: CustomTaskExecutionContext) -> Dict[str, Any]:
        """
        Resolve parameters using context variables and task parameters
        
        Args:
            command: Command whose parameters are being resolved
            context: Execution context with variables
            
        Returns:
            Resolved parameters with substituted values
        """
        parameters = command.parameters or {}
        render_context = {
            **context.parameters,
            **context.variables,
            "parameters": context.parameters,
            "variables": context.variables,
        }
        parser_type = None
        if command.action == "parse_output":
            parser_value = parameters.get("parser") or "regex"
            if isinstance(parser_value, str):
                parser_type = parser_value.lower()

        resolved = {}
        for key, value in parameters.items():
            if (
                command.action == "parse_output"
                and parser_type == "jinja"
                and key in {"template", "pattern"}
                and isinstance(value, str)
            ):
                # Preserve Jinja templates for parsing; defer rendering to parser execution
                resolved[key] = value
                continue

            if isinstance(value, str):
                simple_match = _SIMPLE_TEMPLATE_PATTERN.match(value)
                if simple_match:
                    placeholder_value = self._lookup_context_value(
                        render_context, simple_match.group(1)
                    )
                    if placeholder_value is not None:
                        resolved[key] = placeholder_value
                        continue

            rendered_value = self._render_template_value(value, context)
            if rendered_value is not None:
                resolved[key] = rendered_value
        
        return resolved

    @staticmethod
    def _lookup_context_value(source: Dict[str, Any], path: str) -> Any:
        """Resolve dotted paths against a dict-based context."""
        current: Any = source
        for part in path.split("."):
            if isinstance(current, dict):
                if part in current:
                    current = current[part]
                else:
                    return None
            else:
                if hasattr(current, part):
                    current = getattr(current, part)
                else:
                    return None
        return current
    
    def _resolve_validation_rule(self,
                                 validation_rule: CustomTaskValidationRule,
                                 context: CustomTaskExecutionContext) -> CustomTaskValidationRule:
        """Create a copy of the validation rule with dynamic value resolution."""
        rendered_value = self._render_template_value(validation_rule.value, context)
        if rendered_value is None:
            rendered_value = validation_rule.value
        return replace(validation_rule, value=rendered_value)
    
    def _render_template_value(self, value: Any, context: CustomTaskExecutionContext) -> Any:
        """
        Resolve templated values using context variables and task parameters.
        Returns None if unresolved placeholders remain in a string.
        """
        if isinstance(value, str):
            return self._render_template_string(value, context)
        if isinstance(value, list):
            rendered_list = []
            for item in value:
                rendered_item = self._render_template_value(item, context)
                if rendered_item is None:
                    return None
                rendered_list.append(rendered_item)
            return rendered_list
        if isinstance(value, dict):
            rendered_dict = {}
            for key, item in value.items():
                rendered_item = self._render_template_value(item, context)
                if rendered_item is None:
                    return None
                rendered_dict[key] = rendered_item
            return rendered_dict
        return value
    
    def _render_template_string(self, template: str, context: CustomTaskExecutionContext) -> Optional[str]:
        """Render a template string using Jinja for rich substitutions."""
        if "{{" not in template and "{%" not in template:
            return template

        render_context = {
            **context.parameters,
            **context.variables,
            "parameters": context.parameters,
            "variables": context.variables,
        }

        try:
            compiled = _jinja_env.from_string(template)
            return compiled.render(**render_context)
        except TemplateError as exc:
            logger.debug("Failed to render template '%s': %s", template, exc)
            return None
    
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
        
        # Prepare combined data structure with variables and command results
        command_map = {}
        for cmd_result in command_results:
            cmd_name = cmd_result.get("command_name", "")
            if not cmd_name:
                continue
            command_map[cmd_name] = {
                **cmd_result,
                "result": cmd_result.get("result")
            }

        validation_data = {
            **context.variables,
            "variables": context.variables,
            "commands": command_map
        }
        validation_data.update(command_map)

        # Special handling for common field patterns
        if "." in field_path:
            # Handle dot notation like "ssh_status.result" or "up_interface_count.match_count"
            parts = field_path.split(".")
            base_field = parts[0]

            # Look for the base field in variables first (registered results)
            if base_field in context.variables:
                return context.variables

            # Then look in command results
            if base_field in command_map:
                return validation_data
        else:
            # Simple field name - look in variables first
            if field_path in context.variables:
                return context.variables

            # Then look for command with matching name
            if field_path in command_map:
                return validation_data

        # Default to all available data
        return validation_data

    @staticmethod
    def _stringify_result(result: Any) -> str:
        """Convert structured command results into a human-readable string."""
        if result is None:
            return ""

        if isinstance(result, (dict, list)):
            try:
                return json.dumps(result, indent=2, sort_keys=True)
            except (TypeError, ValueError):
                return str(result)

        return str(result)
