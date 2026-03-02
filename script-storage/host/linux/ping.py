"""
Execute ping from PC1 to Google's public DNS server (8.8.8.8).
"""

import argparse
import json
import sys
import re
from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoTimeoutException, NetmikoAuthenticationException, SSHException

def main():
    parser = argparse.ArgumentParser(description="Execute ping from a Linux host to a target IP.")
    parser.add_argument("--target_ip", required=True, help="The IP address to ping.")
    parser.add_argument("--host", required=True, help="The IP address or hostname of the Linux host.")
    parser.add_argument("--username", required=True, help="Username for SSH access to the Linux host.")
    parser.add_argument("--password", required=True, help="Password for SSH access to the Linux host.")

    args = parser.parse_args()

    device_params = {
        "device_type": "linux", # Use 'linux' for Netmiko to connect to Linux hosts via SSH
        "host": args.host,
        "username": args.username,
        "password": args.password,
        "port": 22, # Default SSH port
    }

    result = {
        "status": "failure",
        "message": "",
        "data": {}
    }

    try:
        with ConnectHandler(**device_params) as net_connect:
            ping_command = f"ping -c 4 {args.target_ip}" # -c 4 sends 4 packets
            output = net_connect.send_command(ping_command)

            # Parse ping output
            ping_data = {
                "destination": args.target_ip,
                "packets_transmitted": 0,
                "packets_received": 0,
                "packet_loss_percent": 100.0,
                "rtt_min_ms": None,
                "rtt_avg_ms": None,
                "rtt_max_ms": None,
                "rtt_mdev_ms": None,
                "raw_output": output
            }

            # Example output parsing:
            # --- 8.8.8.8 ping statistics ---
            # 4 packets transmitted, 4 received, 0% packet loss, time 3004ms
            # rtt min/avg/max/mdev = 9.500/9.875/10.200/0.298 ms
            
            # Packet statistics
            match_stats = re.search(r"(\d+) packets transmitted, (\d+) received, (\d+)% packet loss", output)
            if match_stats:
                ping_data["packets_transmitted"] = int(match_stats.group(1))
                ping_data["packets_received"] = int(match_stats.group(2))
                ping_data["packet_loss_percent"] = float(match_stats.group(3))

            # RTT statistics
            match_rtt = re.search(r"rtt min/avg/max/mdev = (\d+\.?\d*)/(\d+\.?\d*)/(\d+\.?\d*)/(\d+\.?\d*) ms", output)
            if match_rtt:
                ping_data["rtt_min_ms"] = float(match_rtt.group(1))
                ping_data["rtt_avg_ms"] = float(match_rtt.group(2))
                ping_data["rtt_max_ms"] = float(match_rtt.group(3))
                ping_data["rtt_mdev_ms"] = float(match_rtt.group(4))

            result["data"] = ping_data

            if ping_data["packets_received"] > 0 and ping_data["packet_loss_percent"] < 100:
                result["status"] = "success"
                result["message"] = f"Ping to {args.target_ip} successful. {ping_data['packet_loss_percent']}% packet loss."
            else:
                result["status"] = "failure"
                result["message"] = f"Ping to {args.target_ip} failed or had 100% packet loss."

    except NetmikoTimeoutException:
        result["message"] = f"Connection to host {args.host} timed out."
    except NetmikoAuthenticationException:
        result["message"] = f"Authentication failed for host {args.host} with username {args.username}. Please check credentials."
    except SSHException as e:
        result["message"] = f"SSH error connecting to {args.host}: {str(e)}"
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