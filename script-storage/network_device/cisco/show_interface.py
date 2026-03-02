"""
Show Interface Script - Cisco Network Device
Connect via SSH and execute 'show ip interface brief' on a Cisco device.

Usage:
    python show_interface.py --host <IP> --username <USER> --password <PASS>

Output:
    JSON with success, output
    
Note: Requires netmiko library (pip install netmiko)
"""
import argparse
import json
import sys


def show_interface(host: str, username: str, password: str) -> dict:
    """Connect to Cisco device and show interface status."""
    try:
        from netmiko import ConnectHandler

        device = {
            "device_type": "cisco_ios",
            "host": host,
            "username": username,
            "password": password,
            "timeout": 30,
        }

        with ConnectHandler(**device) as conn:
            output = conn.send_command("show ip interface brief")

        return {
            "success": True,
            "output": output.strip()
        }

    except ImportError:
        return {
            "success": False,
            "output": "netmiko library not installed. Run: pip install netmiko"
        }
    except Exception as e:
        return {
            "success": False,
            "output": str(e)
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cisco Show Interface")
    parser.add_argument("--host", required=True, help="Device IP address")
    parser.add_argument("--username", default="admin", help="SSH username")
    parser.add_argument("--password", default="admin", help="SSH password")

    args = parser.parse_args()
    result = show_interface(args.host, args.username, args.password)

    print(json.dumps(result, indent=2))
    sys.exit(0 if result["success"] else 1)
