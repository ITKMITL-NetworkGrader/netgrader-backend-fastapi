"""
Connect to PC1 via SSH
"""

import argparse
import json
import sys
import socket

try:
    import paramiko
except ImportError:
    error_output = {
        "status": "failure",
        "message": "Error: paramiko library not found. Please install it using 'pip install paramiko'."
    }
    print(json.dumps(error_output))
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Connect to a Linux host via SSH using Paramiko.")
    parser.add_argument("--host", required=True, help="Host IP address or hostname")
    parser.add_argument("--username", required=True, help="SSH username")
    parser.add_argument("--password", required=True, help="SSH password")

    args = parser.parse_args()

    client = paramiko.SSHClient()
    # This policy adds the missing host key to the known_hosts file automatically.
    # For production environments, consider a more secure policy like WarningPolicy or RejectPolicy
    # combined with pre-configured known_hosts management.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    result = {
        "status": "failure",
        "message": ""
    }

    try:
        client.connect(hostname=args.host, username=args.username, password=args.password, timeout=10)
        result["status"] = "success"
        result["message"] = f"Successfully connected to {args.username}@{args.host}"

    except paramiko.AuthenticationException:
        result["message"] = f"Authentication failed for {args.username}@{args.host}. Please check username and password."
    except paramiko.SSHException as e:
        result["message"] = f"SSH connection error for {args.host}: {e}"
    except socket.timeout:
        result["message"] = f"Connection timed out while trying to reach {args.host}. Host might be unreachable or SSH service not running."
    except socket.error as e:
        result["message"] = f"Network error connecting to {args.host}: {e}. Check host IP and network connectivity."
    except Exception as e:
        result["message"] = f"An unexpected error occurred: {e}"
    finally:
        # Ensure the client connection is closed if it was established
        if 'client' in locals() and client.get_transport() and client.get_transport().is_active():
            client.close()

    print(json.dumps(result))

    if result["status"] == "success":
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()