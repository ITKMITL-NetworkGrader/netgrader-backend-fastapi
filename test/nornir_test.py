from nornir import InitNornir
from nornir_netmiko import netmiko_send_command, netmiko_send_config
from nornir_napalm.plugins.tasks import napalm_get, napalm_configure
from nornir_utils.plugins.functions import print_result
from nornir.core.filter import F

def execute_task_workflow(nr: InitNornir, task_definitions: list) -> dict:
    """
    Execute tasks dynamically based on task definitions
    """
    results = {}
    
    for task_def in task_definitions:
        task_name = task_def.get("name", "unnamed_task")
        task_filter = task_def.get("filter", {})
        commands = task_def.get("commands", [])
        task_type = task_def.get("type", "netmiko_command")  # default type
        
        # Filter devices if specified
        filtered_nr = nr
        if task_filter:
            if "group" in task_filter:
                filtered_nr = nr.filter(F(groups__contains=task_filter["group"]))
        
        # Execute based on task type
        if task_type == "netmiko_command":
            for command in commands:
                result = filtered_nr.run(
                    task=netmiko_send_command,
                    command_string=command,
                    name=f"{task_name} - {command}"
                )
                results[f"{task_name}_{command}"] = result
        
        elif task_type == "netmiko_config":
            result = filtered_nr.run(
                task=netmiko_send_config,
                config_commands=commands,
                name=task_name
            )
            results[task_name] = result

        elif task_type == "napalm_get":
            getters = task_def.get("getters", ["facts"])
            result = filtered_nr.run(
                task=napalm_get,
                getters=getters,
                name=task_name
            )
            results[task_name] = result
    
    return results

def main():
    nr = InitNornir(config_file="config.yaml")
    
    
    task_definitions = [
        {
            "name": "get_ip_interface",
            "type": "netmiko_config",
            "filter": {
                "group": "cisco_devices"
            },
            "commands": [
                "do sh ip route"
            ]
        },
        {
            "name": "ping_test",
            "type": "netmiko_command", 
            "filter": {
                "group": "cisco_devices"
            },
            "commands": [
                "ping 1.1.1.1"
            ]
        },
        {
            "name": "get_device_facts",
            "type": "napalm_get",
            "filter": {
                "group": "cisco_devices"
            },
            "getters": ["facts",              # Basic device facts
    "interfaces",         # Interface status and config
    "interfaces_ip",      # IP addresses on interfaces
    "interfaces_counters", # Interface statistics
    "arp_table",         # ARP table entries
    "mac_address_table", # MAC address table
    "route_to",       # Routing table (if supported)
    "bgp_neighbors",     # BGP neighbor information
    "lldp_neighbors",    # LLDP neighbor information
]
        }
    ]
    
    results = execute_task_workflow(nr, task_definitions)
    
    # Print results
    for task_name, result in results.items():
        print(f"\n=== {task_name} ===")
        print_result(result)
    # print(results)

main()