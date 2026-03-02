"""
Attempt to establish an SSH connection to PC1
"""

import argparse
import json
import subprocess
import sys

def main():
    parser = argparse.ArgumentParser(description="Attempt to establish an SSH connection to a Linux host (PC1).")
    parser.add_argument("--host", required=True, help="The IP address of the target Linux host.")
    parser.add_argument("--username", required=True, help="The username for SSH authentication.")
    parser.add_argument("--password", required=True, help="The password for SSH authentication.")
    args = parser.parse_args()

    result = {
        "action": "ssh_connect",
        "device_type": "host",
        "os": "linux",
        "host": args.host,
        "username": args.username,
        "status": "failed",
        "message": "",
        "details": {}
    }

    try:
        # Using sshpass to provide password for non-interactive SSH connection
        # -o StrictHostKeyChecking=no and -o UserKnownHostsFile=/dev/null prevent host key prompts
        # The 'exit' command is used to ensure the connection is established and immediately closed
        command = [
            "sshpass",
            "-p", args.password,
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            f"{args.username}@{args.host}",
            "exit"
        ]

        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False
        )

        if process.returncode == 0:
            result["status"] = "success"
            result["message"] = f"Successfully established SSH connection to {args.host}."
            result["details"]["stdout"] = process.stdout.strip()
            result["details"]["stderr"] = process.stderr.strip()
        else:
            result["message"] = f"Failed to establish SSH connection to {args.host}. Error: {process.stderr.strip()}"
            result["details"]["stdout"] = process.stdout.strip()
            result["details"]["stderr"] = process.stderr.strip()

    except FileNotFoundError as e:
        result["message"] = f"Error: Command not found. Ensure 'sshpass' and 'ssh' are installed and in your PATH. {e}"
        result["details"]["error"] = str(e)
    except Exception as e:
        result["message"] = f"An unexpected error occurred: {e}"
        result["details"]["error"] = str(e)

    finally:
        print(json.dumps(result, indent=4))
        if result["status"] == "success":
            sys.exit(0)
        else:
            sys.exit(1)

if __name__ == "__main__":
    main()