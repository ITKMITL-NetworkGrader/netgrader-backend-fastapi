# NetGrader Custom YAML Template Guide

> **Complete reference for creating custom grading task templates**

This document describes the custom YAML template format used in NetGrader for defining network grading tasks. These templates allow instructors to create reusable, configurable grading tasks without writing code.

---

## Template Structure Overview

A custom YAML template consists of the following sections:

```yaml
# Metadata Section
task_name: "template_identifier"
description: "Human-readable description"
connection_type: "netmiko"          # netmiko, ssh, or command
author: "Author Name"
version: "1.0.0"
points: 10

# Parameter Definitions
parameters:
  - name: "param_name"
    datatype: "string"
    description: "Description"
    required: true
    example: "example_value"

# Debug Configuration (Optional)
debug:
  show_command_results: true
  show_registered_variables: true

# Commands Section
commands:
  - name: "command_name"
    action: "action_type"
    parameters:
      key: "value"
    register: "variable_name"

# Validation Section
validation:
  - field: "variable_name"
    condition: "equals"
    value: "expected_value"
    description: "Validation description"
```

---

## Metadata Section

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `task_name` | string | ✅ | Unique identifier for the template (alphanumeric, underscores, hyphens only) |
| `description` | string | ✅ | Human-readable description of what the task does |
| `connection_type` | enum | ✅ | Connection method: `netmiko`, `ssh`, or `command` |
| `author` | string | ❌ | Template author name |
| `version` | string | ❌ | Template version (default: `1.0.0`) |
| `points` | integer | ❌ | Maximum points for this task (default: `10`) |

### Connection Types

| Type | Description | Compatible Actions |
|------|-------------|-------------------|
| `netmiko` | CLI-based device interaction via Netmiko | `netmiko_send_command`, `ping`, `parse_output` |
| `ssh` | Generic SSH connection | `netmiko_send_command`, `ping`, `parse_output` |
| `command` | Direct command execution | `netmiko_send_command`, `parse_output` |

---

## Parameters Section

Define configurable parameters that can be passed at runtime. Parameters support **Jinja2 templating** in commands using `{{parameter_name}}` syntax.

```yaml
parameters:
  - name: "target_ip"
    datatype: "ip_address"
    description: "Target IP address to ping"
    required: true
    example: "192.168.1.100"
  
  - name: "interface_name"
    datatype: "string"
    description: "Interface to check (e.g., GigabitEthernet0/1)"
    required: true
    example: "GigabitEthernet0/1"
```

### Supported Data Types

| Data Type | Description | Validation |
|-----------|-------------|------------|
| `string` | Any text value | Must be a string |
| `integer` | Whole number | Must be parseable as integer |
| `float` | Decimal number | Must be parseable as float |
| `boolean` | True/false value | Accepts `true`, `false`, `1`, `0` |
| `ip_address` | IPv4 address | Must match IPv4 pattern |
| `domain_name` | DNS hostname | Must be valid domain format |
| `cidr` | CIDR notation | Must match `x.x.x.x/y` pattern |

### Union Types

Combine multiple types with the `|` operator:

```yaml
parameters:
  - name: "target"
    datatype: "ip_address | domain_name"
    description: "Target can be IP or hostname"
    required: true
```

---

## Debug Section

Enable debugging features for development and troubleshooting. Debug output appears in the task execution results.

```yaml
debug:
  show_command_results: true          # Show output from each command
  show_registered_variables: true     # Show all stored variables
  show_validation_details: true       # Show detailed validation results
  show_parameter_substitution: true   # Show received parameter values
  custom_debug_points:                # Specific variables to track
    - "ping_result"
    - "success_rate"
```

| Option | Description |
|--------|-------------|
| `show_command_results` | Display output from each executed command |
| `show_registered_variables` | Show all variables stored via `register` |
| `show_validation_details` | Display detailed validation pass/fail information |
| `show_parameter_substitution` | Show the actual parameter values received |
| `custom_debug_points` | List specific variable names to track and display |

---

## Commands Section

Define the sequence of actions to execute. Commands run sequentially and can store results in variables.

### Command Structure

```yaml
commands:
  - name: "descriptive_name"
    action: "action_type"
    parameters:
      key: "value"
      template_key: "{{parameter_name}}"
    register: "result_variable"
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | ✅ | Unique descriptive name for the command |
| `action` | enum | ✅ | Type of action to perform |
| `parameters` | object | ✅ | Action-specific parameters |
| `register` | string | ❌ | Variable name to store the result |

### Supported Actions

#### 1. `netmiko_send_command`

Execute a CLI command on the device using Netmiko.

```yaml
- name: "show_interfaces"
  action: "netmiko_send_command"
  parameters:
    command: "show ip interface brief"
    use_textfsm: true                    # Optional: parse with TextFSM
    textfsm_template: "cisco_ios_show..."  # Optional: custom template
  register: "interface_output"
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `command` | string | ✅ | CLI command to execute |
| `use_textfsm` | boolean | ❌ | Enable TextFSM parsing |
| `textfsm_template` | string | ❌ | Specific TextFSM template name |
| `execution_mode` | string | ❌ | Execution mode configuration |
| `connection_timeout` | integer | ❌ | Connection timeout in seconds |

#### 2. `ping`

Execute a ping test from the device.

```yaml
- name: "test_connectivity"
  action: "ping"
  parameters:
    target_ip: "{{target_ip}}"
    ping_count: 5
  register: "ping_result"
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `target_ip` | string | ✅ | IP address or hostname to ping |
| `ping_count` | integer | ❌ | Number of ping packets (default: 3) |

#### 3. `parse_output`

Parse text output using regex, TextFSM, or Jinja2.

##### Regex Parser (Default)

```yaml
- name: "extract_success_rate"
  action: "parse_output"
  parameters:
    parser: "regex"                      # Optional, default parser
    input: "{{ping_result}}"
    pattern: "Success rate is (\\d+) percent"
  register: "success_rate"
```

**Result structure:**
```yaml
matches: ["80"]           # All captured groups
match_count: 1            # Number of matches
first_match: "80"         # First match or null
```

##### TextFSM Parser

```yaml
- name: "parse_dhcp_bindings"
  action: "parse_output"
  parameters:
    parser: "textfsm"
    input: "{{dhcp_output}}"
    template_path: "/path/to/template.textfsm"
  register: "parsed_dhcp"
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `parser` | string | ✅ | Must be `"textfsm"` |
| `input` | string | ✅ | Text to parse |
| `template_path` | string | ⚠️ | Path to TextFSM template file |
| `template` | string | ⚠️ | Inline TextFSM template content |

> ⚠️ Either `template_path` or `template` is required.

**Result structure:**
```yaml
records:                  # List of parsed records as dictionaries
  - IP_ADDRESS: "192.168.1.10"
    MAC_ADDRESS: "0011.2233.4455"
match_count: 5            # Number of parsed records
template_header: ["IP_ADDRESS", "MAC_ADDRESS"]
```

##### Jinja2 Parser

```yaml
- name: "extract_next_hop"
  action: "parse_output"
  parameters:
    parser: "jinja"
    input: "{{routing_data}}"
    template: |
      {% set entries = input.get(parameters.target_network) or [] %}
      next_hop: {{ entries[0].next_hop if entries else None }}
  register: "next_hop_details"
```

**Result structure:**
```yaml
rendered: "next_hop: 10.0.0.1"    # Raw rendered output
data:                             # Parsed as YAML/JSON if possible
  next_hop: "10.0.0.1"
```

#### 4. `custom_script`

Placeholder for custom script execution (future feature).

```yaml
- name: "custom_check"
  action: "custom_script"
  parameters:
    script_name: "my_script"
  register: "script_result"
```

---

## Validation Section

Define rules to validate execution results. All validations must pass for the task to succeed.

```yaml
validation:
  - field: "success_rate.first_match"
    condition: "greater_than"
    value: 60
    description: "Ping success rate should be greater than 60%"
  
  - field: "interface_output"
    condition: "contains"
    value: "up"
    description: "Interface should be up"
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `field` | string | ✅ | Variable path to validate (supports dot notation) |
| `condition` | enum | ✅ | Validation condition to apply |
| `value` | varies | ✅ | Expected value to compare against |
| `description` | string | ❌ | Human-readable description |

### Supported Conditions

| Condition | Description | Example |
|-----------|-------------|---------|
| `equals` | Exact match | `value: "up"` |
| `contains` | String/list contains value | `value: "Success"` |
| `greater_than` | Numeric comparison > | `value: 50` |
| `less_than` | Numeric comparison < | `value: 90` |
| `regex` | Pattern match | `value: "\\d+ packets"` |
| `exists` | Value exists/non-empty | `value: true` |

### Field Path Syntax

Use dot notation to access nested data:

```yaml
# Access nested dictionary
field: "routing_data.0.0.0.0/0.next_hop"

# Access parser results
field: "success_rate.first_match"
field: "parsed_result.match_count"
field: "parsed_result.records.0.IP_ADDRESS"

# Access Jinja parser output
field: "next_hop_details.data.next_hop"
```

### Dynamic Value Substitution

Use Jinja2 templating in validation values:

```yaml
validation:
  - field: "interface_access_vlan.first_match"
    condition: "equals"
    value: "{{expected_vlan_id}}"
    description: "Interface should be assigned to expected VLAN"
```

---

## Variable System

### Registering Variables

Store command results using the `register` keyword:

```yaml
commands:
  - name: "get_interfaces"
    action: "netmiko_send_command"
    parameters:
      command: "show ip interface brief"
    register: "interface_output"    # Store result in 'interface_output'
```

### Using Variables

Reference variables with Jinja2 syntax:

```yaml
# In command parameters
parameters:
  input: "{{interface_output}}"

# In validation fields
field: "interface_output"

# In validation values
value: "{{expected_value}}"
```

### Variable Scope

- **Task Parameters**: Available as `{{parameter_name}}`
- **Registered Variables**: Available as `{{variable_name}}`
- **In Jinja Parser**: Access via `parameters.name` or `variables.name`

---

## Complete Examples

### Example 1: Advanced Ping Test

```yaml
task_name: "advanced_ping_test"
description: "Multi-stage ping with success rate validation"
connection_type: "netmiko"
author: "NetGrader Team"
version: "1.0.0"
points: 12

parameters:
  - name: "target_ip"
    datatype: "ip_address | domain_name"
    description: "Target to ping"
    required: true
    example: "192.168.1.100"

commands:
  - name: "initial_ping"
    action: "ping"
    parameters:
      target_ip: "{{target_ip}}"
      ping_count: 5
    register: "ping_result"
  
  - name: "parse_success"
    action: "parse_output"
    parameters:
      input: "{{ping_result}}"
      pattern: "Success rate is (\\d+) percent"
    register: "success_rate"

validation:
  - field: "success_rate.first_match"
    condition: "greater_than"
    value: 60
    description: "Ping success rate must exceed 60%"
```

### Example 2: VLAN Verification

```yaml
task_name: "vlan_verification"
description: "Verify VLAN configuration and assignments"
connection_type: "netmiko"
author: "NetGrader Team"
version: "1.0.0"
points: 15

parameters:
  - name: "interface_name"
    datatype: "string"
    description: "Interface to check"
    required: true
    example: "GigabitEthernet0/1"
  - name: "expected_vlan_id"
    datatype: "integer"
    description: "Expected VLAN ID"
    required: true
    example: "100"

commands:
  - name: "show_vlan_brief"
    action: "netmiko_send_command"
    parameters:
      command: "show vlan brief"
    register: "vlan_output"
  
  - name: "check_interface_vlan"
    action: "netmiko_send_command"
    parameters:
      command: "show interface {{interface_name}} switchport"
    register: "interface_vlan"
  
  - name: "parse_access_vlan"
    action: "parse_output"
    parameters:
      input: "{{interface_vlan}}"
      pattern: "Access Mode VLAN:\\s+(\\d+)"
    register: "access_vlan"

validation:
  - field: "access_vlan.first_match"
    condition: "equals"
    value: "{{expected_vlan_id}}"
    description: "Interface should be on expected VLAN"
  
  - field: "interface_vlan"
    condition: "contains"
    value: "Switchport: Enabled"
    description: "Switchport must be enabled"
```

### Example 3: Linux Service Health Check

```yaml
task_name: "linux_service_health"
description: "Check service status on Linux server"
connection_type: "ssh"
author: "NetGrader Team"
version: "1.0.0"
points: 8

commands:
  - name: "check_ssh"
    action: "netmiko_send_command"
    parameters:
      command: "systemctl is-active sshd"
    register: "ssh_status"
  
  - name: "check_network"
    action: "netmiko_send_command"
    parameters:
      command: "ip link show | grep 'state UP'"
    register: "network_interfaces"
  
  - name: "count_up_interfaces"
    action: "parse_output"
    parameters:
      input: "{{network_interfaces}}"
      pattern: "state UP"
    register: "up_count"
  
  - name: "check_disk"
    action: "netmiko_send_command"
    parameters:
      command: "df -h / | tail -n 1 | awk '{print $5}' | sed 's/%//'"
    register: "disk_usage"

validation:
  - field: "ssh_status"
    condition: "contains"
    value: "active"
    description: "SSH service must be active"
  
  - field: "up_count.match_count"
    condition: "greater_than"
    value: 0
    description: "At least one interface must be up"
  
  - field: "disk_usage"
    condition: "less_than"
    value: 90
    description: "Disk usage must be below 90%"
```

---

## Template Location

Templates are loaded from the `custom_tasks/` directory relative to the application root. Each `.yaml` file in this directory is automatically registered using its `task_name` field.

```
netgrader-backend-fastapi/
├── custom_tasks/
│   ├── advanced_ping_test.yaml
│   ├── vlan_verification.yaml
│   └── linux_service_health.yaml
```

---

## Using Templates in Grading Jobs

Reference templates by `task_name` in your grading job payload:

```json
{
  "network_tasks": [
    {
      "task_id": "verify_vlan",
      "name": "Verify VLAN 100",
      "template_name": "vlan_verification",
      "execution_device": "switch1",
      "parameters": {
        "interface_name": "GigabitEthernet0/1",
        "expected_vlan_id": 100
      },
      "points": 15
    }
  ]
}
```

> **Note**: The `points` value in the job payload overrides the template's default points.

---

## Best Practices

1. **Use Descriptive Names**: Make `task_name` and command names clearly indicate their purpose
2. **Provide Examples**: Always include `example` values in parameter definitions
3. **Write Clear Descriptions**: Help other instructors understand what validations check
4. **Use Debug During Development**: Enable debug options to troubleshoot template issues
5. **Validate Early**: Add validation rules that catch common configuration errors
6. **Reuse Patterns**: Create utility templates for common checks (ping, interface status, etc.)
7. **Version Your Templates**: Update the `version` field when making changes

---

*Last Updated: December 2024*
