"""
Execute traceroute from PC1 to 1.1.1.1
"""

import argparse
import json
import sys
import paramiko

def main():
    """
    Executes a traceroute command from a remote Linux host to a specified target IP.
    """
    parser = argparse.ArgumentParser(
        description="Execute traceroute from a remote Linux host to a target IP."
    )
    parser.add_argument(
        '--target_ip',
        type=str,
        default='1.1.1.1',
        help='The target IP address for traceroute (e.g., 1.1.1.1).'
    )
    parser.add_argument(
        '--host',
        type=str,
        required=True,
        help='The IP address or hostname of the remote Linux host (e.g., 10.70.38.253).'
    )
    parser.add_argument(
        '--username',
        type=str,
        required=True,
        help='Username for SSH connection to the remote Linux host (e.g., ubuntu).'
    )
    parser.add_argument(
        '--password',
        type=str,
        required=True,
        help='Password for SSH connection to the remote Linux host (e.g., ubuntu).'
    )

    args = parser.parse_args()

    # Initialize result dictionary
    result = {
        "status": "failure",
        "message": "",
        "data": {}
    }

    ssh_client = paramiko.SSHClient()
    # AutoAddPolicy is used here for simplicity in automation.
    # In production, consider using WarningPolicy or a known_hosts file.
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        # Establish SSH connection to the remote Linux host
        ssh_client.connect(
            hostname=args.host,
            username=args.username,
            password=args.password,
            timeout=10
        )

        # Construct the traceroute command
        # Using -n to prevent DNS lookups for faster and more consistent output
        command = f"traceroute -n {args.target_ip}"
        
        # Execute the command on the remote host
        # A timeout of 5 minutes (300 seconds) is given for traceroute to complete
        stdin, stdout, stderr = ssh_client.exec_command(command, timeout=300)
        
        stdout_output = stdout.read().decode('utf-8').strip()
        stderr_output = stderr.read().decode('utf-8').strip()
        exit_status = stdout.channel.recv_exit_status() # Get the exit status of the remote command

        if exit_status == 0:
            result["status"] = "success"
            result["message"] = f"Traceroute from {args.host} to {args.target_ip} executed successfully."
            result["data"]["target_ip"] = args.target_ip
            result["data"]["source_host"] = args.host
            result["data"]["traceroute_output"] = stdout_output
            if stderr_output:
                result["data"]["warnings"] = stderr_output
        else:
            result["message"] = (
                f"Traceroute command failed on {args.host}. "
                f"Exit status: {exit_status}. Stderr: {stderr_output}. Stdout: {stdout_output}"
            )
            result["data"]["target_ip"] = args.target_ip
            result["data"]["source_host"] = args.host
            result["data"]["error_output"] = stderr_output
            result["data"]["raw_stdout"] = stdout_output
            
            # Check for common "command not found" errors
            if "command not found" in stderr_output.lower() or "not found" in stderr_output.lower():
                result["message"] = (
                    f"Traceroute command not found on host {args.host}. "
                    f"Please ensure 'traceroute' is installed. Stderr: {stderr_output}"
                )

    except paramiko.AuthenticationException:
        result["message"] = f"Authentication failed for user {args.username} on host {args.host}. " \
                            f"Please check username and password."
    except paramiko.SSHException as e:
        result["message"] = f"Could not establish SSH connection to {args.host}: {e}. " \
                            f"Check host availability and SSH service."
    except TimeoutError:
        result["message"] = f"SSH connection or command execution timed out for host {args.host}. " \
                            f"The host might be unreachable or the command took too long."
    except Exception as e:
        result["message"] = f"An unexpected error occurred: {e}"
    finally:
        # Ensure the SSH connection is closed
        if ssh_client:
            ssh_client.close()

    # Print the JSON output to stdout
    print(json.dumps(result, indent=2))

    # Exit with appropriate status code
    if result["status"] == "success":
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()