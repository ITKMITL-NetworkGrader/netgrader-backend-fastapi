# YAML DSL Plugin Examples

This directory contains example YAML DSL task definitions that instructors can use as templates for creating custom network testing tasks.

## YAML DSL Syntax

### Basic Structure
```yaml
template_name: "my_custom_task"
description: "Description of what this task does"
connection_type: "napalm"  # napalm, netmiko, or ssh

steps:
  - name: "Step description"
    action: "action_name"
    parameter1: "value1"
    parameter2: "{{ variable_name }}"
    register: "result_variable"
    when: "condition_expression"
```

### Available Actions

1. **ping** - Test connectivity
2. **command** - Execute custom command
3. **parse_output** - Parse command output with regex/TextFSM
4. **set_result** - Set final task result status
5. **assert** - Make assertions about data

### Variables and Templating

- Use Jinja2 syntax: `{{ variable_name }}`
- Access task parameters: `{{ target_ip }}`
- Access IP mappings: `{{ pc1_ip }}`
- Access previous step results: `{{ ping_result.success_rate }}`

### Example Usage

See the example files in this directory for complete task definitions.