"""
Get the IP address of PC2's interface and verify it's within the DHCP assigned range (172.50.174.197 - 172.50.174.202).
"""

import argparse
import json
import sys
import telnetlib
import ipaddress
import re

def main():
    parser = argparse.ArgumentParser(description="Get IP address of a Linux host interface and verify against a DHCP range via Telnet.")
    parser.add_argument("--connectionType", type=str, default="Telnet", help="Type of connection (e.g., Telnet).")
    parser.add_argument("--connectionHost", type=str, required=True, help="Hostname or IP address of the device.")
    parser.add_argument("--connectionPort", type=int, required=True, help="Port number for the connection.")
    parser.add_argument("--username", type=str, required=True, help="Username for authentication.")
    parser.add_argument("--password", type=str, required=True, help="Password for authentication.")
    parser.add_argument("--expectedIpRangeStart", type=str, required=True, help="Start of the expected IP address range.")
    parser.add_argument("--expectedIpRangeEnd", type=str, required=True, help="End of the expected IP address range.")
    parser.add_argument("--interface", type=str, default=None, help="Specific interface name to check (e.g., eth0). If None, will find the first non-loopback IP.")

    args = parser.parse_args()

    result_data = {
        "status": "failure",
        "message": "",
        "ip_address": None,
        "interface": args.interface,
        "expected_range_start": args.expectedIpRangeStart,
        "expected_range_end": args.expectedIpRangeEnd
    }

    tn = None # Initialize telnetlib object

    try:
        # Validate IP range
        expected_ip_start = ipaddress.IPv4Address(args.expectedIpRangeStart)
        expected_ip_end = ipaddress.IPv4Address(args.expectedIpRangeEnd)
        if expected_ip_start > expected_ip_end:
            raise ValueError("Expected IP range start cannot be greater than end.")

        # Establish Telnet connection
        try:
            tn = telnetlib.Telnet(args.connectionHost, args.connectionPort, timeout=10)
        except Exception as e:
            result_data["message"] = f"Failed to connect to Telnet host {args.connectionHost}:{args.connectionPort}. Error: {e}"
            print(json.dumps(result_data, indent=2))
            sys.exit(1)
        
        # Login sequence
        tn.read_until(b"login: ", timeout=5)
        tn.write(args.username.encode('ascii') + b"\n")
        
        tn.read_until(b"Password: ", timeout=5)
        tn.write(args.password.encode('ascii') + b"\n")

        # Read any initial output and check for login failure
        login_output = tn.read_until(b"", timeout=5).decode('ascii', errors='ignore')
        if "Login incorrect" in login_output or "Authentication failed" in login_output:
            result_data["message"] = "Telnet login failed. Check username and password."
            print(json.dumps(result_data, indent=2))
            sys.exit(1)
        
        # Execute 'ip -4 a' command to get IPv4 addresses and use a marker for output end
        tn.write(b"ip -4 a\n")
        tn.write(b"echo ___END_OF_COMMAND___\n") # Marker to identify the end of the command output
        
        full_output = tn.read_until(b"___END_OF_COMMAND___", timeout=10).decode('ascii', errors='ignore')
        
        # Check for command execution errors on the remote host
        if "command not found" in full_output.lower():
            result_data["message"] = "Command 'ip -4 a' not found or failed on the remote host."
            print(json.dumps(result_data, indent=2))
            sys.exit(1)

        # Parse 'ip -4 a' output to extract IP address
        current_interface = None
        found_ip_str = None
        lines = full_output.splitlines()
        
        # Regex to find IP addresses like 'inet 192.168.1.100/24 scope global'
        ip_pattern = re.compile(r'inet (\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})/\d{1,2}\s+scope global')

        for i, line in enumerate(lines):
            # Identify interface lines (e.g., "2: eth0:")
            interface_match = re.match(r'^\d+: ([^:]+):', line.strip())
            if interface_match:
                current_interface = interface_match.group(1)
            
            # Identify IP address lines for the current interface
            ip_match = ip_pattern.search(line)
            if ip_match:
                extracted_ip = ip_match.group(1)
                
                # If a specific interface is requested
                if args.interface:
                    if current_interface == args.interface:
                        found_ip_str = extracted_ip
                        result_data["interface"] = current_interface
                        break # Found the IP for the specified interface
                else: # If no specific interface, take the first non-loopback global IP
                    if current_interface and current_interface != 'lo':
                        found_ip_str = extracted_ip
                        result_data["interface"] = current_interface
                        break # Found the first non-loopback IP
        
        if not found_ip_str:
            result_data["message"] = f"No IP address found for interface '{args.interface or 'any non-loopback interface'}'."
            print(json.dumps(result_data, indent=2))
            sys.exit(1)

        result_data["ip_address"] = found_ip_str
        
        # Verify extracted IP against the expected range
        actual_ip = ipaddress.IPv4Address(found_ip_str)
        if expected_ip_start <= actual_ip <= expected_ip_end:
            result_data["status"] = "success"
            result_data["message"] = f"IP address {found_ip_str} on interface {result_data['interface']} is within the expected range ({args.expectedIpRangeStart}-{args.expectedIpRangeEnd})."
        else:
            result_data["message"] = f"IP address {found_ip_str} on interface {result_data['interface']} is NOT within the expected range ({args.expectedIpRangeStart}-{args.expectedIpRangeEnd})."
            # Status remains 'failure' as initialized

    except ipaddress.AddressValueError as e:
        result_data["message"] = f"Invalid IP address format provided in range parameters or extracted IP. Error: {e}"
    except ValueError as e:
        result_data["message"] = f"Configuration error: {e}"
    except Exception as e:
        result_data["message"] = f"An unexpected error occurred: {e}"
    finally:
        if tn:
            tn.close() # Close Telnet connection
        
        print(json.dumps(result_data, indent=2))
        
        if result_data["status"] == "success":
            sys.exit(0)
        else:
            sys.exit(1)

if __name__ == "__main__":
    main()