"""
Verify PC2 has received an IP address via DHCP from Router1 within the range 172.50.174.197-202.
"""

import argparse
import json
import subprocess
import sys
import re
import ipaddress

def get_ip_address_linux(interface):
    """
    Retrieves the primary IPv4 address for a given network interface on a Linux host.
    """
    try:
        command = ["ip", "addr", "show", "dev", interface]
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        output = process.stdout
        # Regex to find an IPv4 address (e.g., 192.168.1.100/24)
        match = re.search(r'inet (\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})/\d{1,2}', output)
        if match:
            return match.group(1)
        return None
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Command failed: {' '.join(command)}. Stderr: {e.stderr}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Command timed out: {' '.join(command)}")
    except FileNotFoundError:
        raise RuntimeError("The 'ip' command was not found. Is 'iproute2' installed?")

def auto_detect_interface():
    """
    Attempts to automatically detect an active, non-loopback interface with an IP address.
    """
    try:
        command = ["ip", "-br", "addr", "show"]
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        output = process.stdout
        lines = output.strip().split('\n')
        for line in lines:
            parts = line.split()
            if len(parts) >= 3 and parts[1] == 'UP' and parts[0] != 'lo':
                # Check if it has an IP address assigned
                if 'inet' in line or 'brd' in line: # Simple check for IP presence
                    return parts[0] # Return interface name
        return None
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to auto-detect interface. Command failed: {' '.join(command)}. Stderr: {e.stderr}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Auto-detect interface command timed out: {' '.join(command)}")
    except FileNotFoundError:
        raise RuntimeError("The 'ip' command was not found. Is 'iproute2' installed?")


def main():
    parser = argparse.ArgumentParser(description="Verify PC2's IP address on a Linux host.")
    parser.add_argument("--interface", type=str, default="auto",
                        help="Network interface to check (e.g., eth0, ens33). Use 'auto' to detect.")
    parser.add_argument("--expected_ip_from_dhcp", type=str, default="true",
                        help="Flag indicating if IP is expected via DHCP. 'true' or 'false'.")
    parser.add_argument("--expected_dhcp_server_device", type=str,
                        help="Expected DHCP server device name (e.g., Router1).")
    parser.add_argument("--expected_ip_range_start", type=str, required=True,
                        help="Start of the expected IP address range (e.g., 172.50.174.197).")
    parser.add_argument("--expected_ip_range_end", type=str, required=True,
                        help="End of the expected IP address range (e.g., 172.50.174.202).")

    args = parser.parse_args()

    result = {
        "status": "failure",
        "message": "Script execution started.",
        "parameters": {
            "interface": args.interface,
            "expected_ip_from_dhcp": args.expected_ip_from_dhcp,
            "expected_dhcp_server_device": args.expected_dhcp_server_device,
            "expected_ip_range_start": args.expected_ip_range_start,
            "expected_ip_range_end": args.expected_ip_range_end
        },
        "found_ip": None,
        "is_in_range": False,
        "checked_interface": None
    }

    try:
        if args.interface == "auto":
            current_interface = auto_detect_interface()
            if not current_interface:
                raise RuntimeError("Could not automatically detect an active network interface with an IP address.")
            result["checked_interface"] = current_interface
            result["message"] = f"Automatically detected interface: {current_interface}"
        else:
            current_interface = args.interface
            result["checked_interface"] = current_interface
            result["message"] = f"Checking specified interface: {current_interface}"

        found_ip = get_ip_address_linux(current_interface)
        result["found_ip"] = found_ip

        if not found_ip:
            raise RuntimeError(f"No IPv4 address found on interface '{current_interface}'.")

        try:
            start_ip = ipaddress.IPv4Address(args.expected_ip_range_start)
            end_ip = ipaddress.IPv4Address(args.expected_ip_range_end)
            current_ip = ipaddress.IPv4Address(found_ip)
        except ipaddress.AddressValueError:
            raise ValueError("Invalid IP address format for range start, end, or found IP.")

        if start_ip <= current_ip <= end_ip:
            result["is_in_range"] = True
            result["status"] = "success"
            result["message"] = (f"Successfully verified IP {found_ip} on {current_interface}. "
                                 f"It is within the expected range {args.expected_ip_range_start}-"
                                 f"{args.expected_ip_range_end}.")
        else:
            result["status"] = "failure"
            result["message"] = (f"IP address {found_ip} on {current_interface} is NOT within the expected range "
                                 f"{args.expected_ip_range_start}-{args.expected_ip_range_end}.")

    except RuntimeError as e:
        result["status"] = "failure"
        result["message"] = str(e)
    except ValueError as e:
        result["status"] = "failure"
        result["message"] = f"Configuration Error: {e}"
    except Exception as e:
        result["status"] = "failure"
        result["message"] = f"An unexpected error occurred: {e}"

    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "success" else 1)

if __name__ == "__main__":
    main()