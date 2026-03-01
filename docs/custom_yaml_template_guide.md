# NetGrader Custom YAML Template Guide (Refactored Runtime)

> **Current reference for creating custom grading task templates**

This guide documents the **actual behavior in the current refactored backend** (`CustomTaskRegistry` + `CustomTaskExecutor`).

---

## What Changed in the Refactor

- Templates are now loaded as **global templates from MinIO**, not from local disk at runtime.
- `template_name` in grading payload maps to a global template and is converted internally to `custom_task_id`.
- `connection_type` is no longer used by the runtime.
- All `netmiko_send_command` actions inside a single template execution now share one connection automatically.
- `parse_output` now has consistent parser modes (`regex`, `textfsm`, `jinja`) and supports `register_as: raw`.
- Validation supports `not_equals` in addition to previous conditions.

---

## Template Structure (Current)

```yaml
task_name: "vlan_verification"
description: "Verify VLAN configuration"
author: "NetGrader Team"
version: "1.0.0"
points: 15

parameters:
  - name: "interface_name"
    datatype: "string"
    description: "Interface to validate"
    required: true
    example: "GigabitEthernet0/1"

debug:
  show_command_results: true
  show_registered_variables: true
  show_validation_details: true
  show_parameter_substitution: true
  custom_debug_points:
    - "result_var"

commands:
  - name: "run_command"
    action: "netmiko_send_command"
    parameters:
      command: "show ip interface brief"
    register: "raw_output"

  - name: "parse_result"
    action: "parse_output"
    parameters:
      parser: "regex"
      input: "{{raw_output}}"
      pattern: "up"
    register: "parsed"

validation:
  - field: "parsed.match_count"
    condition: "greater_than"
    value: 0
    description: "At least one match must exist"
```

---

## Metadata Fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `task_name` | string | ✅ | Must be unique and match `[a-zA-Z0-9_-]+` |
| `description` | string | ✅ | Human-readable description |
| `author` | string | ❌ | Optional |
| `version` | string | ❌ | Default `1.0.0` |
| `points` | number | ❌ | Default `10` |

### Important

- `connection_type` is **ignored** by current runtime and should not be relied on.

---

## Parameters

Parameters are defined in `parameters` and can be referenced with Jinja syntax:

- `{{parameter_name}}`
- `{{parameters.parameter_name}}`

### Supported datatypes

- `string`
- `integer`
- `float`
- `boolean`
- `ip_address` (IPv4)
- `domain_name`
- `cidr`
- `ipv6_address`

### Union types

Use `|` to allow multiple datatypes:

```yaml
datatype: "ip_address | domain_name"
```

### Runtime coercion behavior

- `integer` / `float`: string values are coerced when possible.
- `boolean`: accepts `true/false`, `1/0`, `yes/no` (case-insensitive).
- Optional parameter with `null` or empty string is accepted without type validation.

---

## Commands

Commands execute sequentially.

```yaml
- name: "command_name"
  action: "action_type"
  parameters:
    key: "value"
  register: "variable_name"
  register_as: "raw"
```

| Field | Required | Notes |
|---|---|---|
| `name` | ✅ | Must be unique in template |
| `action` | ✅ | One of supported actions |
| `parameters` | ❌ | Defaults to `{}` |
| `register` | ❌ | Stores command result into context variable |
| `register_as` | ❌ | Only supports `raw`; requires `register`; only valid for `parse_output` and `netmiko_send_command` |

### Supported actions

- `netmiko_send_command`
- `ping`
- `parse_output`
- `custom_script` (placeholder, not implemented)

---

## Action Details

### 1) `netmiko_send_command`

Runs command via Nornir command executor.

```yaml
- name: "show_interfaces"
  action: "netmiko_send_command"
  parameters:
    command: "show ip interface brief"
    read_timeout: 30
    last_read: 2.0
    execution_mode: "isolated"
    stateful_session_id: "session-1"
    connection_timeout: 30
    use_textfsm: true
    textfsm_template: "/path/template.textfsm"
  register: "interfaces"
```

#### Parameters forwarded by custom executor

- `command` (required)
- `read_timeout` (optional, default `30` seconds, range `1`-`120`)
- `last_read` (optional, timing-based read window, range `0.5`-`30`)
- `use_textfsm` (optional, parse using ntc-templates lookup)
- `textfsm_template` (optional, custom template path or inline template content)

#### Connection behavior for `netmiko_send_command`

- Commands share a single isolated connection for the full template execution.
- The shared connection is created only when at least one `netmiko_send_command` exists in the template.
- `execution_mode` and `stateful_session_id` are accepted for backward compatibility but are deprecated and log warnings.
- `connection_timeout` is ignored by the shared-command path and logs a warning.

If `register_as: raw` is used, raw metadata is stored:

```yaml
raw_output: "..."
structured_output: [...]
```

---

### 2) `ping`

Runs ping through Nornir ping task.

```yaml
- name: "test_connectivity"
  action: "ping"
  parameters:
    target_ip: "{{target_ip}}"
    ping_count: 5
  register: "ping_result"
```

#### Parameters

- `target_ip` (required)
- `ping_count` (optional, default `3`)

Result stored is the ping task `stdout` string.

---

### 3) `parse_output`

Parses command output using one of three parser types.

```yaml
- name: "parse_step"
  action: "parse_output"
  parameters:
    parser: "regex"
    input: "{{some_output}}"
    pattern: "..."
  register: "parsed"
```

#### Parser: `regex` (default)

Required: `pattern`

```yaml
parameters:
  input: "{{ping_result}}"
  pattern: "Success rate is (\\d+) percent"
```

Registered result shape:

```yaml
matches: [...]
match_count: 1
first_match: "80"
```

With `register_as: raw`, additional metadata includes `input` and `pattern`.

#### Parser: `textfsm`

Required: `template` (**inline template content**)

```yaml
parameters:
  parser: "textfsm"
  input: "{{raw_cli}}"
  template: |
    Value IP_ADDRESS (\S+)

    Start
      ^${IP_ADDRESS} -> Record
```

> Current runtime expects `template` content. `template_path` is **not supported** in the parser action.

Registered result (flat) is a list of parsed records:

```yaml
- IP_ADDRESS: "192.168.1.10"
```

With `register_as: raw`, metadata includes:

```yaml
template_header: [...]
records: [...]
raw_matches: [...]
match_count: 1
input: "..."
```

#### Parser: `jinja`

Required: `template` (or `pattern` as fallback).

```yaml
parameters:
  parser: "jinja"
  input: "{{binding_output}}"
  template: |
    {% set bindings = input if input is sequence and input is not string and input is not mapping else [] %}
    leased_ips: {{ bindings[0].ip_address if bindings | length > 0 else [] }}
```

Behavior:

- Renders Jinja using context variables:
  - `input`
  - `parameters`
  - `variables`
- Attempts to parse rendered output as JSON, then YAML.
- If parsing fails, keeps rendered string.

Registered result is the parsed object/string.

With `register_as: raw`, metadata includes:

```yaml
input: ...
rendered: "..."
data: ...
```

---

### 4) `custom_script`

Placeholder only.

Returns a static message indicating custom script execution is not implemented yet.

---

## Variable System

### Registering

```yaml
register: "variable_name"
```

- On command success: registered value is command `result`.
- On command failure: registered value is error text (`stderr`).

### Referencing

Use Jinja in command parameters and validation values:

- `{{variable_name}}`
- `{{variables.variable_name}}`
- `{{parameter_name}}`
- `{{parameters.parameter_name}}`

### Nested lookup

Dot notation works for dict/list paths in validation fields:

- `access_vlan.first_match`
- `parsed.records.0.IP_ADDRESS`

---

## Validation

Each rule:

```yaml
- field: "success_rate.first_match"
  condition: "greater_than"
  value: 60
  description: "Success must exceed 60%"
```

### Supported conditions

- `equals`
- `not_equals`
- `contains`
- `greater_than`
- `less_than`
- `regex`
- `exists`

### Notes

- `exists` accepts boolean-like expectations (`true/false`, `yes/no`, `1/0`).
- Validation `value` supports Jinja templating and is rendered at runtime.
- All validations must pass for final task status to be `passed`.
- If there are **no validations**, success is based on command success ratio (`> 50%` successful commands).

---

## Debug Output

Optional `debug` controls extra output and callback debug payload:

- `show_command_results`
- `show_registered_variables`
- `show_validation_details`
- `show_parameter_substitution`
- `custom_debug_points`

When enabled, debug data is also included in API result `debug_info`.

---

## Template Loading (Refactored)

Runtime loads templates from MinIO bucket under prefix:

```text
custom_tasks/
```

Examples:

```text
custom_tasks/vlan_verification.yaml
custom_tasks/dhcp_binding.yaml
```

`STRICT_MODE=true` causes startup failure if any template fails validation.

---

## Using Templates in Grading Jobs

In grading job payload, reference template with `template_name`:

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

Runtime maps it to custom execution and sets:

```json
{
  "custom_task_id": "vlan_verification"
}
```

`points` in job payload overrides template default points.

---

## Authoring Tips

1. Keep command names unique and descriptive.
2. Prefer explicit parser mode (`parser: regex|textfsm|jinja`) for readability.
3. Use `register_as: raw` only when you need parser metadata.
4. Validate parsed fields (e.g., `.match_count`, `.first_match`) instead of raw text whenever possible.
5. Enable debug options while developing, then reduce noise for production templates.

---

*Last Updated: February 2026*
