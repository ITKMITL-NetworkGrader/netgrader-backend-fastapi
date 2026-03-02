"""
Ping Google (8.8.8.8) from PC1
"""

import argparse
import json
import sys
import re
from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoTimeoutException, NetmikoAuthenticationException, SSHException

def main():
    parser = argparse.ArgumentParser(description="Ping a target IP from a remote Linux host.")
    parser.add_argument("--target_ip", required=True, help="IP address to ping (e.g., 8.8.8.8).")
    parser.add_argument("--host", required=True, help="IP address or hostname of the remote Linux host.")
    parser.add_argument("--username", required=True, help="Username for SSH connection to the remote host.")
    parser.add_argument("--password", required=True, help="Password for SSH connection to the remote host.")

    args = parser.parse_args()

    device = {
        "device_type": "linux", # Netmiko supports 'linux' for generic Linux hosts via SSH
        "host": args.host,
        "username": args.username,
        "password": args.password,
        "global_delay_factor": 2 # Increase delay for slower SSH connections if needed
    }

    result = {
        "status": "failure",
        "message": "",
        "data": {}
    }

    try:
        with ConnectHandler(**device) as net_connect:
            ping_command = f"ping -c 4 {args.target_ip}"
            output = net_connect.send_command(ping_command, cmd_verify=False)

            result["data"]["raw_output"] = output

            # Regex to parse ping output
            packet_loss_match = re.search(r"(\d+)% packet loss", output)
            transmitted_match = re.search(r"(\d+) packets transmitted", output)
            received_match = re.search(r"(\d+) received", output)
            rtt_match = re.search(r"rtt min/avg/max/mdev = (\d+\.?\d*)/(\d+\.?\d*)/(\d+\.?\d*)/(\d+\.?\d*) ms", output)

            if packet_loss_match and transmitted_match and received_match:
                packet_loss = int(packet_loss_match.group(1))
                transmitted_packets = int(transmitted_match.group(1))
                received_packets = int(received_match.group(1))
                
                result["data"]["packet_loss_percent"] = packet_loss
                result["data"]["transmitted_packets"] = transmitted_packets
                result["data"]["received_packets"] = received_packets

                if packet_loss == 0:
                    result["status"] = "success"
                    result["message"] = f"Ping to {args.target_ip} from {args.host} successful with 0% packet loss."
                    if rtt_match:
                        result["data"]["rtt_min_ms"] = float(rtt_match.group(1))
                        result["data"]["rtt_avg_ms"] = float(rtt_match.group(2))
                        result["data"]["rtt_max_ms"] = float(rtt_match.group(3))
                        result["data"]["rtt_mdev_ms"] = float(rtt_match.group(4))
                else:
                    result["message"] = f"Ping to {args.target_ip} from {args.host} failed with {packet_loss}% packet loss."
            else:
                result["message"] = "Could not parse ping output for packet loss information. Check raw_output for details."

    except NetmikoTimeoutException:
        result["message"] = f"Connection to remote host {args.host} timed out. Check IP address, network connectivity, or SSH service."
    except NetmikoAuthenticationException:
        result["message"] = f"Authentication failed for user '{args.username}' on host {args.host}. Check username and password."
    except SSHException as e:
        result["message"] = f"SSH connection error to {args.host}: {str(e)}"
    except Exception as e:
        result["message"] = f"An unexpected error occurred: {str(e)}"
    finally:
        print(json.dumps(result, indent=2))
        if result["status"] == "success":
            sys.exit(0)
        else:
            sys.exit(1)

if __name__ == "__main__":
    main()