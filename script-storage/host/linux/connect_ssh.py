"""
Connect to PC1 via SSH to prepare for ping operation
"""

import argparse
import subprocess
import json
import sys
import os

def connect_ssh(host, username, password):
    """
    Connects to a Linux host via SSH using subprocess and verifies connectivity.
    It uses sshpass for password-based authentication.
    """
    # Construct the SSH command.
    # -o StrictHostKeyChecking=no and UserKnownHostsFile=/dev/null are used for automation
    # to bypass host key prompts, but should be used with caution in production.
    # -o BatchMode=yes prevents interactive prompts.
    # -o ConnectTimeout=10 sets a timeout for the connection.
    # 'true' is a simple command to execute on the remote host to verify connection.
    ssh_command_base = [
        'ssh',
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'UserKnownHostsFile=/dev/null',
        '-o', 'BatchMode=yes',
        '-o', 'ConnectTimeout=10',
        f'{username}@{host}',
        'echo "SSH connection successful"'
    ]

    # Use sshpass for password-based authentication
    # Check if sshpass is installed.
    if os.environ.get('SSH_ASKPASS'):
        # If SSH_ASKPASS is set, it might interfere with sshpass.
        # Unset it for this subprocess call.
        env = os.environ.copy()
        del env['SSH_ASKPASS']
    else:
        env = None

    try:
        # Check if sshpass is available.
        subprocess.run(['sshpass', '-V'], check=True, capture_output=True, text=True)
        cmd = ['sshpass', '-p', password] + ssh_command_base
    except (subprocess.CalledProcessError, FileNotFoundError):
        # sshpass not found or failed, try without it (will likely fail for password auth)
        # or raise an error asking for sshpass.
        # Given the prompt includes "password", sshpass is implied for subprocess.
        return {
            "status": "failure",
            "message": "Error: 'sshpass' command not found. For password-based SSH with subprocess, sshpass is required. Please install it.",
            "host": host,
            "username": username,
            "error_type": "sshpass_not_found"
        }

    try:
        # Execute the command
        process = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)

        return {
            "status": "success",
            "message": f"Successfully connected to {host} via SSH.",
            "host": host,
            "username": username,
            "stdout": process.stdout.strip(),
            "stderr": process.stderr.strip()
        }
    except subprocess.CalledProcessError as e:
        # SSH command returned a non-zero exit code (failure)
        return {
            "status": "failure",
            "message": f"Failed to connect to {host} via SSH. {e.stderr.strip()}",
            "host": host,
            "username": username,
            "stdout": e.stdout.strip(),
            "stderr": e.stderr.strip(),
            "return_code": e.returncode
        }
    except FileNotFoundError:
        # This should ideally be caught by the sshpass check above,
        # but as a fallback for 'ssh' itself.
        return {
            "status": "failure",
            "message": f"Error: 'ssh' command not found. Ensure SSH client is installed and in PATH.",
            "host": host,
            "username": username,
            "error_type": "ssh_client_not_found"
        }
    except Exception as e:
        # Catch any other unexpected errors
        return {
            "status": "failure",
            "message": f"An unexpected error occurred while connecting to {host}: {str(e)}",
            "host": host,
            "username": username,
            "error_type": "unexpected_error"
        }

def main():
    parser = argparse.ArgumentParser(description="Connect to a Linux host via SSH to prepare for ping operation.")
    parser.add_argument('--host', required=True, help='The IP address or hostname of the Linux host.')
    parser.add_argument('--username', required=True, help='The username for SSH authentication.')
    parser.add_argument('--password', required=True, help='The password for SSH authentication.')

    args = parser.parse_args()

    # Perform the SSH connection attempt
    result = connect_ssh(args.host, args.username, args.password)

    # Print the result as JSON
    print(json.dumps(result, indent=2))

    # Exit with appropriate status code
    if result.get("status") == "success":
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == '__main__':
    main()