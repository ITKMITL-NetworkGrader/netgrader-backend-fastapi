"""
Global Task Template Registry - Auto-load global task templates from MinIO

This service automatically loads task templates from YAML files stored in MinIO.
Templates are globally available and referenced directly by their task_name.
"""

import asyncio
import logging
import yaml
from typing import Dict, Any, List, Optional, Union, TYPE_CHECKING, Tuple
from dataclasses import dataclass
from pathlib import Path
from enum import Enum
from app.core.config import config
from app.services.grading.ipv6_utils import is_valid_ipv6


if TYPE_CHECKING:
    from app.services.connectivity.minio_service import MinioService

logger = logging.getLogger(__name__)




class CustomTaskValidationCondition(Enum):
    """Supported validation conditions"""
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    REGEX = "regex"
    EXISTS = "exists"


@dataclass
class CustomTaskValidationRule:
    """Represents a validation rule for custom task results"""
    field: str
    condition: CustomTaskValidationCondition
    value: Union[str, int, float, bool]
    description: Optional[str] = None


@dataclass
class CustomTaskCommand:
    """Represents a command within a custom task"""
    name: str
    action: str
    parameters: Dict[str, Any]
    register: Optional[str] = None  # Variable name to store result
    register_as: Optional[str] = None  # "raw" to keep full parser metadata


@dataclass
class CustomTaskParameter:
    """Represents a parameter definition for a custom task"""
    name: str
    datatype: str
    description: str
    required: bool = True
    example: Optional[str] = None


@dataclass
class CustomTaskDebugConfig:
    """Debug configuration for custom task"""
    show_command_results: bool = False
    show_registered_variables: bool = False
    show_validation_details: bool = False
    show_parameter_substitution: bool = False
    custom_debug_points: List[str] = None  # Specific variables/commands to debug


@dataclass
class CustomTaskDefinition:
    """Complete definition of a global task template"""
    task_name: str
    description: str
    commands: List[CustomTaskCommand]
    validation_rules: List[CustomTaskValidationRule]
    parameters: List[CustomTaskParameter] = None
    debug_config: Optional[CustomTaskDebugConfig] = None
    author: Optional[str] = None
    version: str = "1.0.0"
    points: float = 10.0


class CustomTaskValidationError(Exception):
    """Raised when task template validation fails"""
    pass


class CustomTaskRegistry:
    """
    Registry for global task templates that are auto-loaded from MinIO.
    
    Templates are loaded automatically from YAML files stored in MinIO bucket
    under the 'custom_tasks/' prefix and made available globally using their
    task_name as the identifier.
    """
    
    # Prefix for custom task objects in MinIO
    DEFAULT_PREFIX = f"{config.CUSTOM_TASK_REGISTRY_DIR}/"
    
    def __init__(
        self,
        minio_service: Optional["MinioService"] = None,
        bucket_name: str = config.MINIO_BUCKET_NAME,
        strict_mode: bool = config.STRICT_MODE,
    ):
        """
        Initialize the global task template registry
        
        Args:
            minio_service: MinioService instance for loading templates from MinIO
            bucket_name: MinIO bucket name containing task templates
            strict_mode: If True, raise on any template load failure during startup
        """
        self._minio_service = minio_service
        self._bucket_name = bucket_name
        self._strict_mode = strict_mode
        
        # Cache for loaded templates using task_name as key
        self._template_cache: Dict[str, CustomTaskDefinition] = {}
        self._failed_templates: List[str] = []  # Track templates that failed to load
        self._initialized = False
        
    async def initialize(self) -> None:
        """
        Async initialization - load all templates from MinIO.
        Must be called after construction before using the registry.
        """
        if self._initialized:
            return
            
        if self._minio_service:
            await self._load_templates_from_minio()
        else:
            logger.warning("No MinIO service provided, registry will be empty")
            
        self._initialized = True
        logger.info(f"Global task registry initialized with {len(self._template_cache)} templates from MinIO bucket '{self._bucket_name}'")
    
    def get_template(self, task_name: str) -> Optional[CustomTaskDefinition]:
        """
        Get a global task template by its task_name
        
        Args:
            task_name: Name of the task template (from YAML task_name field)
            
        Returns:
            CustomTaskDefinition if found, None otherwise
        """
        return self._template_cache.get(task_name)
    
    def get_custom_task(self, task_name: str) -> Optional[CustomTaskDefinition]:
        """
        Retrieve a global task template by name (alias for get_template for compatibility)
        
        Args:
            task_name: Name of the task template
            
        Returns:
            CustomTaskDefinition if found, None otherwise
        """
        return self.get_template(task_name)
    
    def list_templates(self) -> List[str]:
        """
        List all available global template names
        
        Returns:
            List of template task names
        """
        return list(self._template_cache.keys())

    def upsert_template(self, definition: CustomTaskDefinition) -> None:
        """Insert or replace a template definition in the in-memory registry cache."""
        self._template_cache[definition.task_name] = definition

    def remove_template(self, task_name: str) -> None:
        """Remove a template definition from the in-memory registry cache."""
        self._template_cache.pop(task_name, None)

    def register_temporary_template_from_yaml(
        self,
        yaml_content: str,
        task_name_override: Optional[str] = None,
        register: bool = True,
    ) -> CustomTaskDefinition:
        """
        Parse, validate, and register a temporary template from raw YAML content.

        This does not persist to MinIO. It is intended for live test-preview flows.
        """
        try:
            template_data = yaml.safe_load(yaml_content)
        except Exception as exc:
            raise CustomTaskValidationError(f"Invalid YAML: {exc}") from exc

        if not isinstance(template_data, dict):
            raise CustomTaskValidationError("YAML content must be an object")

        if task_name_override:
            template_data["task_name"] = task_name_override

        if "task_name" not in template_data:
            raise CustomTaskValidationError("task_name is required")

        definition = self._create_task_definition_from_dict(template_data)
        self._validate_definition(definition, is_global_template=True)
        if register:
            self.upsert_template(definition)
        return definition
    
    def is_global_template(self, task_name: str) -> bool:
        """
        Check if a task name corresponds to a global template
        
        Args:
            task_name: Task name to check
            
        Returns:
            True if it's a global template, False otherwise
        """
        return task_name in self._template_cache
    
    async def reload_templates(self) -> int:
        """
        Reload all templates from MinIO
        
        Returns:
            Number of templates loaded
        """
        self._template_cache.clear()
        return await self._load_templates_from_minio()
    
    def prepare_parameters(self, task_name: str, parameters: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        """
        Convert and validate parameters in a single pass.
        
        Args:
            task_name: Name of the task template
            parameters: Raw parameters (may contain string values)
            
        Returns:
            Tuple of (typed_parameters: Dict, errors: List[str])
        """
        template = self.get_template(task_name)
        if not template:
            return parameters, [f"Template '{task_name}' not found"]
        
        if not template.parameters:
            return parameters, []
        
        type_map = {p.name: p.datatype for p in template.parameters}
        required_map = {p.name: p.required for p in template.parameters}
        
        typed_params = {}
        errors = []
        
        # Check for missing required parameters
        for param_def in template.parameters:
            if param_def.required and param_def.name not in parameters:
                errors.append(f"Required parameter '{param_def.name}' is missing")
        
        # Convert and validate each parameter
        for key, value in parameters.items():
            expected_type = type_map.get(key)
            is_required = required_map.get(key, False)
            
            # Skip validation for optional parameters with empty/None values
            if not is_required and (value is None or value == ""):
                typed_params[key] = value
                continue
            
            # Convert string values to proper types
            if expected_type and isinstance(value, str):
                typed_value = self._coerce_value(value, expected_type)
            else:
                typed_value = value
            
            typed_params[key] = typed_value
            
            # Validate the converted value
            if expected_type:
                validation_error = self._validate_type(key, typed_value, expected_type)
                if validation_error:
                    errors.append(validation_error)
        
        return typed_params, errors
    
    def _coerce_value(self, value: str, expected_type: str) -> Any:
        if "|" in expected_type:
            for type_option in (t.strip() for t in expected_type.split("|")):
                coerced = self._coerce_value(value, type_option)
                if coerced is not value:
                    return coerced
            return value
        
        if expected_type == "boolean":
            lower_val = value.lower()
            if lower_val in ("true", "1", "yes"):
                return True
            elif lower_val in ("false", "0", "no"):
                return False
        elif expected_type == "integer":
            try:
                return int(value)
            except (ValueError, TypeError):
                pass
        elif expected_type == "float":
            try:
                return float(value)
            except (ValueError, TypeError):
                pass
        return value
    
    def _validate_type(self, param_name: str, value: Any, expected_type: str) -> Optional[str]:
        """Validate a parameter value against its expected type (after conversion)."""
        # Handle union types
        if "|" in expected_type:
            type_options = [t.strip() for t in expected_type.split("|")]
            for type_option in type_options:
                if self._validate_type(param_name, value, type_option) is None:
                    return None
            return f"Parameter '{param_name}' must be {' or '.join(type_options)}"
        
        # Simple type checks (values should already be converted)
        if expected_type == "string":
            if not isinstance(value, str):
                return f"'{param_name}' must be a string, got {type(value).__name__}"
        
        elif expected_type == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                return f"'{param_name}' must be an integer, got {type(value).__name__}"
        
        elif expected_type == "float":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return f"'{param_name}' must be a number, got {type(value).__name__}"
        
        elif expected_type == "boolean":
            if not isinstance(value, bool):
                return f"'{param_name}' must be a boolean, got {type(value).__name__}"
        
        elif expected_type == "ip_address":
            import re
            if not isinstance(value, str):
                return f"'{param_name}' must be an IP address string"
            ip_pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
            if not re.match(ip_pattern, value):
                return f"'{param_name}' must be a valid IP address, got '{value}'"
        
        elif expected_type == "domain_name":
            import re
            if not isinstance(value, str):
                return f"'{param_name}' must be a domain name string"
            domain_pattern = r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$'
            if not re.match(domain_pattern, value) or len(value) > 253:
                return f"'{param_name}' must be a valid domain name, got '{value}'"
        
        elif expected_type == "cidr":
            import re
            if not isinstance(value, str):
                return f"'{param_name}' must be a CIDR notation string"
            cidr_pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\/(?:[0-9]|[1-2][0-9]|3[0-2])$'
            if not re.match(cidr_pattern, value):
                return f"'{param_name}' must be valid CIDR notation, got '{value}'"
        
        elif expected_type == "ipv6_address":
            if not isinstance(value, str):
                return f"'{param_name}' must be an IPv6 address string"
            if not is_valid_ipv6(value):
                return f"'{param_name}' must be a valid IPv6 address, got '{value}'"
        
        return None
    
    def get_parameter_info(self, task_name: str) -> Dict[str, Any]:
        """Get parameter information for a template."""
        template = self.get_template(task_name)
        if not template:
            return {"error": f"Template '{task_name}' not found"}
        
        if not template.parameters:
            return {"parameters": [], "message": "No parameters defined"}
        
        param_info = []
        for param in template.parameters:
            param_info.append({
                "name": param.name,
                "datatype": param.datatype,
                "description": param.description,
                "required": param.required,
                "example": param.example
            })
        
        return {"task_name": task_name, "parameters": param_info}
    
    
    def _create_task_definition_from_dict(self, task_data: Dict[str, Any]) -> CustomTaskDefinition:
        """
        Factory method to create CustomTaskDefinition from dictionary
        
        Args:
            task_data: Dictionary containing task definition
            
        Returns:
            CustomTaskDefinition object
        """
        # Parse commands
        commands = []
        for cmd_data in task_data.get("commands", []):
            register_as_raw = cmd_data.get("register_as")
            register_as_val = register_as_raw.strip().lower() if isinstance(register_as_raw, str) else register_as_raw
            command = CustomTaskCommand(
                name=cmd_data["name"],
                action=cmd_data["action"],
                parameters=cmd_data.get("parameters", {}),
                register=cmd_data.get("register"),
                register_as=register_as_val
            )
            commands.append(command)
        
        # Parse validation rules
        validation_rules = []
        for rule_data in task_data.get("validation", []):
            rule = CustomTaskValidationRule(
                field=rule_data["field"],
                condition=CustomTaskValidationCondition(rule_data["condition"]),
                value=rule_data["value"],
                description=rule_data.get("description")
            )
            validation_rules.append(rule)
        
        # Parse parameters
        parameters = []
        params_data = task_data.get("parameters", [])
        if params_data:
            for param_data in params_data:
                if isinstance(param_data, dict) and "name" in param_data:
                    parameter = CustomTaskParameter(
                        name=param_data["name"],
                        datatype=param_data["datatype"],
                        description=param_data["description"],
                        required=param_data.get("required", True),
                        example=param_data.get("example")
                    )
                    parameters.append(parameter)
        
        # Parse debug configuration
        debug_config = None
        debug_data = task_data.get("debug")
        if debug_data:
            debug_config = CustomTaskDebugConfig(
                show_command_results=debug_data.get("show_command_results", False),
                show_registered_variables=debug_data.get("show_registered_variables", False),
                show_validation_details=debug_data.get("show_validation_details", False),
                show_parameter_substitution=debug_data.get("show_parameter_substitution", False),
                custom_debug_points=debug_data.get("custom_debug_points", [])
            )
        

        # Create task definition
        return CustomTaskDefinition(
            task_name=task_data["task_name"],
            description=task_data["description"],
            commands=commands,
            validation_rules=validation_rules,
            parameters=parameters if parameters else None,
            debug_config=debug_config,
            author=task_data.get("author"),
            version=task_data.get("version", "1.0.0"),
            points=task_data.get("points", 10)
        )
    
    _VALID_REGISTER_AS = {"raw"}
    _REGISTER_AS_ACTIONS = {"parse_output", "netmiko_send_command"}

    def _validate_commands(self, commands: List[CustomTaskCommand]) -> List[str]:
        """Validate commands — shared by _validate_template and _validate_task_definition."""
        errors = []
        supported_actions = [
            "netmiko_send_command", "ping",
            "parse_output", "custom_script"
        ]
        seen_names = set()
        for i, command in enumerate(commands):
            if not command.name or not command.name.strip():
                errors.append(f"Command {i}: name is required")
            elif command.name in seen_names:
                errors.append(f"Command {i}: duplicate command name '{command.name}'")
            else:
                seen_names.add(command.name)

            if not command.action or not command.action.strip():
                errors.append(f"Command {i}: action is required")
            if command.action not in supported_actions:
                errors.append(f"Command {i}: unsupported action '{command.action}'")

            if command.register_as is not None:
                if command.register_as not in self._VALID_REGISTER_AS:
                    errors.append(
                        f"Command {i}: register_as must be one of {self._VALID_REGISTER_AS}, "
                        f"got '{command.register_as}'"
                    )
                if not command.register:
                    errors.append(f"Command {i}: register_as requires register to be set")
                if command.action not in self._REGISTER_AS_ACTIONS:
                    errors.append(
                        f"Command {i}: register_as is not supported for action '{command.action}'"
                    )
        return errors

    def _validate_definition(self, definition: CustomTaskDefinition, is_global_template: bool = False) -> None:
        """
        Validate a custom task definition.
        
        Args:
            definition: CustomTaskDefinition to validate
            is_global_template: If True, apply stricter template naming rules
            
        Raises:
            CustomTaskValidationError: If validation fails
        """
        errors = []
        
        # Basic field validation
        if not definition.task_name or not definition.task_name.strip():
            errors.append("task_name is required and cannot be empty")
        
        # Global template names must be valid identifiers (no spaces, special chars)
        if is_global_template and definition.task_name:
            if not definition.task_name.replace('_', '').replace('-', '').isalnum():
                errors.append("task_name must contain only letters, numbers, underscores, and hyphens")
        
        if not definition.description or not definition.description.strip():
            errors.append("description is required and cannot be empty")
        
        if not definition.commands:
            errors.append("At least one command is required")
        
        errors.extend(self._validate_commands(definition.commands))
        
        if errors:
            prefix = "Template validation failed: " if is_global_template else ""
            raise CustomTaskValidationError(f"{prefix}{'; '.join(errors)}")
    
    async def _list_yaml_objects(self) -> List[str]:
        """List all YAML object names from MinIO under the custom_tasks/ prefix."""
        object_names: List[str] = []
        async for obj_name in self._minio_service.list_objects(
            bucket_name=self._bucket_name,
            prefix=self.DEFAULT_PREFIX,
            recursive=True
        ):
            if obj_name.endswith('.yaml') or obj_name.endswith('.yml'):
                object_names.append(obj_name)
        return object_names

    async def _load_one_template(self, object_name: str) -> CustomTaskDefinition:
        """Download, parse, validate, and return a single template from MinIO."""
        yaml_bytes = await self._minio_service.download_data(
            object_name=object_name,
            bucket_name=self._bucket_name
        )
        template_data = yaml.safe_load(yaml_bytes.decode('utf-8'))
        
        if not template_data or 'task_name' not in template_data:
            raise CustomTaskValidationError(f"missing task_name in {object_name}")
        
        task_definition = self._create_task_definition_from_dict(template_data)
        self._validate_definition(task_definition, is_global_template=True)
        return task_definition

    def _summarize_failures(self, failed: List[str]) -> None:
        """Store and log failed template details; raise in strict mode."""
        self._failed_templates = failed
        logger.error(
            f"{len(failed)} template(s) failed to load (valid templates still loaded): "
            + "; ".join(failed)
        )
        if self._strict_mode:
            raise CustomTaskValidationError(
                f"{len(failed)} template(s) failed validation during startup: "
                + "; ".join(failed)
            )

    async def _load_templates_from_minio(self) -> int:
        """Load global task templates from YAML files stored in MinIO.
        
        Objects are expected at: custom_tasks/<task-name>.yaml
        """
        if not self._minio_service:
            logger.warning("No MinIO service provided, cannot load templates")
            return 0
            
        loaded_count = 0
        self._failed_templates = []  # Reset on each load/reload
        
        try:
            object_names = await self._list_yaml_objects()
            logger.debug(f"Found {len(object_names)} YAML files in MinIO bucket '{self._bucket_name}'")
            
            failed_templates: List[str] = []
            for object_name in object_names:
                try:
                    task_definition = await self._load_one_template(object_name)
                    self._template_cache[task_definition.task_name] = task_definition
                    loaded_count += 1
                    logger.debug(f"Loaded global template: {task_definition.task_name} from {object_name}")
                except Exception as e:
                    failed_templates.append(f"{object_name}: {e}")
                    logger.error(f"Failed to load template from MinIO object '{object_name}': {e}")
            
            if failed_templates:
                self._summarize_failures(failed_templates)

        except CustomTaskValidationError:
            raise
        except Exception as e:
            logger.error(f"Failed to list templates from MinIO bucket '{self._bucket_name}': {e}")
            return 0
        
        logger.info(f"Loaded {loaded_count} global task templates from MinIO")
        if self._failed_templates:
            logger.warning(
                f"{len(self._failed_templates)} template(s) need migration: "
                + "; ".join(self._failed_templates)
            )
        return loaded_count

    def get_health_status(self) -> Dict[str, Any]:
        """Return template registry health status for monitoring/health checks."""
        return {
            "initialized": self._initialized,
            "loaded_count": len(self._template_cache),
            "loaded_templates": list(self._template_cache.keys()),
            "failed_count": len(self._failed_templates),
            "failed_templates": list(self._failed_templates),
            "healthy": self._initialized and len(self._failed_templates) == 0,
        }
