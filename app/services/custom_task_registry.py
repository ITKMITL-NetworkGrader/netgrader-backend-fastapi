"""
Global Task Template Registry - Auto-load global task templates from directory

This service automatically loads task templates from YAML files in a directory.
Templates are globally available and referenced directly by their task_name.
"""

import logging
import yaml
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)


class CustomTaskConnectionType(Enum):
    """Supported connection types for custom tasks"""
    NAPALM = "napalm"
    NETMIKO = "netmiko" 
    SSH = "ssh"
    COMMAND = "command"


class CustomTaskValidationCondition(Enum):
    """Supported validation conditions"""
    EQUALS = "equals"
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
    connection_type: CustomTaskConnectionType
    commands: List[CustomTaskCommand]
    validation_rules: List[CustomTaskValidationRule]
    parameters: List[CustomTaskParameter] = None
    debug_config: Optional[CustomTaskDebugConfig] = None
    author: Optional[str] = None
    version: str = "1.0.0"
    points: int = 10


class CustomTaskValidationError(Exception):
    """Raised when task template validation fails"""
    pass


class CustomTaskRegistry:
    """
    Registry for global task templates that are auto-loaded from a directory.
    
    Templates are loaded automatically from YAML files and made available
    globally using their task_name as the identifier (no prefix/suffix).
    """
    
    def __init__(self, registry_dir: str = "custom_tasks"):
        """
        Initialize the global task template registry
        
        Args:
            registry_dir: Directory containing global task template YAML files
        """
        self.templates_dir = Path(registry_dir)
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        
        # Cache for loaded templates using task_name as key
        self._template_cache: Dict[str, CustomTaskDefinition] = {}
        
        # Load all templates on initialization
        self._load_global_templates()
        
        logger.info(f"Global task registry initialized with {len(self._template_cache)} templates from {self.templates_dir}")
    
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
    
    def is_global_template(self, task_name: str) -> bool:
        """
        Check if a task name corresponds to a global template
        
        Args:
            task_name: Task name to check
            
        Returns:
            True if it's a global template, False otherwise
        """
        return task_name in self._template_cache
    
    def reload_templates(self) -> int:
        """
        Reload all templates from the directory
        
        Returns:
            Number of templates loaded
        """
        self._template_cache.clear()
        return self._load_global_templates()
    
    def validate_parameters(self, task_name: str, parameters: Dict[str, Any]) -> List[str]:
        """
        Validate parameters against template parameter definitions
        
        Args:
            task_name: Name of the task template
            parameters: Parameters to validate
            
        Returns:
            List of validation error messages (empty if valid)
        """
        template = self.get_template(task_name)
        if not template:
            return [f"Template '{task_name}' not found"]
        
        if not template.parameters:
            # No parameters defined, accept any parameters
            return []
        
        errors = []
        
        # Check required parameters
        for param_def in template.parameters:
            if param_def.required and param_def.name not in parameters:
                errors.append(f"Required parameter '{param_def.name}' is missing")
                continue
            
            if param_def.name in parameters:
                param_value = parameters[param_def.name]
                validation_error = self._validate_parameter_type(
                    param_def.name, param_value, param_def.datatype
                )
                if validation_error:
                    errors.append(validation_error)
        
        return errors
    
    def get_parameter_info(self, task_name: str) -> Dict[str, Any]:
        """
        Get parameter information for a template
        
        Args:
            task_name: Name of the task template
            
        Returns:
            Dictionary with parameter information
        """
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
        
        return {
            "task_name": task_name,
            "parameters": param_info
        }
    
    def _validate_parameter_type(self, param_name: str, value: Any, expected_type: str) -> Optional[str]:
        """
        Validate a parameter value against its expected type(s)
        
        Supports union types using | separator (e.g., "ip_address | domain_name")
        Uses recursive calls to handle union types
        
        Args:
            param_name: Parameter name
            value: Parameter value
            expected_type: Expected data type(s), can be single or union with |
            
        Returns:
            Error message if validation fails, None if valid
        """
        # Handle union types recursively (e.g., "ip_address | domain_name")
        if "|" in expected_type:
            type_options = [t.strip() for t in expected_type.split("|")]
            errors = []
            
            # Recursively try each type option - if any passes, validation succeeds
            for type_option in type_options:
                error = self._validate_parameter_type(param_name, value, type_option)
                if error is None:
                    return None  # Validation passed for this type
                errors.append(f"({type_option}: {error})")
            
            # All type options failed, return combined error
            type_list = " or ".join(type_options)
            return f"Parameter '{param_name}' must be {type_list}. Failed validations: {'; '.join(errors)}"
        
        # Single type validation
        if expected_type == "string":
            if not isinstance(value, str):
                return f"must be a string, got {type(value).__name__}"
        
        elif expected_type == "integer":
            if not isinstance(value, int):
                try:
                    int(value)
                except (ValueError, TypeError):
                    return f"must be an integer, got {type(value).__name__}"
        
        elif expected_type == "float":
            if not isinstance(value, (int, float)):
                try:
                    float(value)
                except (ValueError, TypeError):
                    return f"must be a number, got {type(value).__name__}"
        
        elif expected_type == "boolean":
            if not isinstance(value, bool):
                if str(value).lower() not in ["true", "false", "1", "0"]:
                    return f"must be a boolean (true/false), got {value}"
        
        elif expected_type == "ip_address":
            import re
            if not isinstance(value, str):
                return f"must be an IP address string"
            
            ip_pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
            if not re.match(ip_pattern, value):
                return f"must be a valid IP address, got '{value}'"
        
        elif expected_type == "domain_name":
            if not isinstance(value, str):
                return f"must be a domain name string"
            
            # Domain name regex pattern
            domain_pattern = r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$'
            if not re.match(domain_pattern, value) or len(value) > 253:
                return f"must be a valid domain name, got '{value}'"
        
        elif expected_type == "cidr":
            import re
            if not isinstance(value, str):
                return f"must be a CIDR notation string"
            
            # CIDR pattern (e.g., 192.168.1.0/24)
            cidr_pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\/(?:[0-9]|[1-2][0-9]|3[0-2])$'
            if not re.match(cidr_pattern, value):
                return f"must be valid CIDR notation (e.g., 10.0.24.0/24), got '{value}'"
        
        else:
            # Unknown type, treat as string but warn
            logger.warning(f"Unknown parameter type '{expected_type}' for parameter '{param_name}', treating as string")
            if not isinstance(value, str):
                return f"must be a string (unknown type '{expected_type}'), got {type(value).__name__}"
        
        return None
    
    
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
            command = CustomTaskCommand(
                name=cmd_data["name"],
                action=cmd_data["action"],
                parameters=cmd_data.get("parameters", {}),
                register=cmd_data.get("register")
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
            connection_type=CustomTaskConnectionType(task_data["connection_type"]),
            commands=commands,
            validation_rules=validation_rules,
            parameters=parameters if parameters else None,
            debug_config=debug_config,
            author=task_data.get("author"),
            version=task_data.get("version", "1.0.0"),
            points=task_data.get("points", 10)
        )
    
    def _validate_task_definition(self, definition: CustomTaskDefinition) -> None:
        """
        Validate a custom task definition
        
        Args:
            definition: CustomTaskDefinition to validate
            
        Raises:
            CustomTaskValidationError: If validation fails
        """
        errors = []
        
        # Basic field validation
        if not definition.task_name or not definition.task_name.strip():
            errors.append("task_name is required and cannot be empty")
        
        if not definition.description or not definition.description.strip():
            errors.append("description is required and cannot be empty")
        
        if not definition.commands:
            errors.append("At least one command is required")
        
        # Validate commands
        for i, command in enumerate(definition.commands):
            if not command.name or not command.name.strip():
                errors.append(f"Command {i}: name is required")
            
            if not command.action or not command.action.strip():
                errors.append(f"Command {i}: action is required")
            
            # Validate supported actions
            supported_actions = [
                "napalm_get", "netmiko_send_command", "ping", 
                "ssh_connect", "parse_output", "custom_script"
            ]
            if command.action not in supported_actions:
                errors.append(f"Command {i}: unsupported action '{command.action}'")
        
        # Validate connection type compatibility
        napalm_actions = ["napalm_get"]
        netmiko_actions = ["netmiko_send_command"]
        
        for i, command in enumerate(definition.commands):
            if (definition.connection_type == CustomTaskConnectionType.NAPALM and 
                command.action not in napalm_actions and
                command.action not in ["ping", "parse_output", "custom_script"]):
                errors.append(f"Command {i}: action '{command.action}' incompatible with NAPALM connection")
        
        if errors:
            raise CustomTaskValidationError("; ".join(errors))
    
    def _validate_template(self, definition: CustomTaskDefinition) -> None:
        """
        Validate a global task template definition
        
        Args:
            definition: CustomTaskDefinition to validate
            
        Raises:
            CustomTaskValidationError: If validation fails
        """
        errors = []
        
        # Basic field validation
        if not definition.task_name or not definition.task_name.strip():
            errors.append("task_name is required and cannot be empty")
        
        # Global template names must be valid identifiers (no spaces, special chars)
        if not definition.task_name.replace('_', '').replace('-', '').isalnum():
            errors.append("task_name must contain only letters, numbers, underscores, and hyphens")
        
        if not definition.description or not definition.description.strip():
            errors.append("description is required and cannot be empty")
        
        if not definition.commands:
            errors.append("At least one command is required")
        
        # Validate commands
        for i, command in enumerate(definition.commands):
            if not command.name or not command.name.strip():
                errors.append(f"Command {i}: name is required")
            
            if not command.action or not command.action.strip():
                errors.append(f"Command {i}: action is required")
            
            # Validate supported actions for global templates
            supported_actions = [
                "napalm_get", "netmiko_send_command", "ping", 
                "ssh_connect", "parse_output", "custom_script"
            ]
            if command.action not in supported_actions:
                errors.append(f"Command {i}: unsupported action '{command.action}'")
        
        if errors:
            raise CustomTaskValidationError(f"Template validation failed: {'; '.join(errors)}")
    
    
    def _load_global_templates(self) -> int:
        """Load global task templates from YAML files in directory"""
        if not self.templates_dir.exists():
            logger.warning(f"Templates directory does not exist: {self.templates_dir}")
            return 0
            
        loaded_count = 0
        
        # Load global task templates directly from YAML files
        for yaml_file in self.templates_dir.glob("*.yaml"):
            try:
                with open(yaml_file, 'r', encoding='utf-8') as f:
                    template_data = yaml.safe_load(f)
                
                if not template_data or 'task_name' not in template_data:
                    logger.warning(f"Invalid template file (missing task_name): {yaml_file}")
                    continue
                
                # Create task definition directly from YAML data
                task_definition = self._create_task_definition_from_dict(template_data)
                
                # Validate the task definition
                self._validate_template(task_definition)
                
                # Store in cache using task_name as key (no prefix/suffix)
                self._template_cache[task_definition.task_name] = task_definition
                loaded_count += 1
                
                logger.debug(f"Loaded global template: {task_definition.task_name} from {yaml_file.name}")
                
            except Exception as e:
                logger.warning(f"Failed to load template from {yaml_file}: {e}")
        
        logger.info(f"Loaded {loaded_count} global task templates from directory")
        return loaded_count
    
