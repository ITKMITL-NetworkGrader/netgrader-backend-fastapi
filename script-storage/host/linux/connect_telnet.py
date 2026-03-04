"""
Connect to PC2 via Telnet console.
"""

import argparse
import json
import subprocess
import sys
import time
import re

def main():
    parser = argparse.ArgumentParser(description="Connect to a Linux host via Telnet console and attempt login.")
    parser.add_argument("--host", required=True, help="Target host IP or hostname.")
    parser.add_argument("--port", type=int, required=True, help="Target Telnet port.")
    parser.add_argument("--username", required=True, help="Username for Telnet login.")
    parser.add_argument("--password", required=True, help="Password for Telnet login.")

    args = parser.parse_args()

    # Initialize result dictionary
    result = {
        "status": "failure",
        "action": "connect_telnet",
        "host": args.host,
        "port": args.port,
        "error": "Unknown error occurred",
        "output": ""
    }
    process = None
    output_buffer = ""
    exit_code = 1  # Default to failure

    try:
        # Start the telnet process using Popen to manage stdin/stdout
        # stderr is merged into stdout for easier capture.
        # text=True handles encoding/decoding as UTF-8.
        # bufsize=1 enables line buffering.
        process = subprocess.Popen(
            ['telnet', args.host, str(args.port)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merge stderr into stdout
            text=True,
            bufsize=1
        )

        # Helper function to read from stdout until a pattern is found or timeout
        def read_until_pattern(pattern, timeout=5):
            nonlocal output_buffer
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    # readline() blocks until a newline or EOF, but with small sleeps
                    # and the loop timeout, it attempts to read chunks over time.
                    # This approach is a best-effort simulation of pexpect-like behavior
                    # using only subprocess and basic Python modules. It is inherently
                    # fragile compared to libraries like pexpect.
                    line = process.stdout.readline()
                    if line:
                        output_buffer += line
                        if re.search(pattern, output_buffer, re.IGNORECASE | re.DOTALL):
                            return True
                except ValueError:
                    # Raised if stdin/stdout pipe is closed prematurely
                    pass
                time.sleep(0.1)  # Small delay to prevent busy-waiting
            return False

        # --- Step 1: Wait for initial connection and login prompt ---
        if not read_until_pattern(r'(login|username):|connect refused|connection closed', timeout=10):
            result["error"] = "Initial login/username prompt or connection status not detected within timeout."
            raise Exception("No initial prompt or connection status.")

        if re.search(r'connect refused|connection closed', output_buffer, re.IGNORECASE | re.DOTALL):
            result["error"] = "Telnet connection refused or closed by remote host."
            raise Exception("Connection refused/closed.")

        # --- Step 2: Send username ---
        if re.search(r'(login|username):', output_buffer, re.IGNORECASE | re.DOTALL):
            process.stdin.write(f"{args.username}\n")
            process.stdin.flush()
            output_buffer += f"[SENT] {args.username}\n"

            # --- Step 3: Wait for password prompt ---
            if not read_until_pattern(r'password:', timeout=5):
                result["error"] = "Password prompt not detected after sending username."
                raise Exception("No password prompt.")

            # --- Step 4: Send password ---
            if re.search(r'password:', output_buffer, re.IGNORECASE | re.DOTALL):
                process.stdin.write(f"{args.password}\n")
                process.stdin.flush()
                output_buffer += f"[SENT] {args.password}\n"

                # --- Step 5: Wait for successful login prompt or failure message ---
                if not read_until_pattern(r'(\$|#|welcome|last login|successfully authenticated|failed|denied|incorrect|invalid)', timeout=10):
                    result["error"] = "Login attempt completed, but neither success nor explicit failure prompt detected."
                    raise Exception("No final login status.")

                # --- Step 6: Determine login success or failure ---
                if re.search(r'(\$|#|welcome|last login|successfully authenticated)', output_buffer, re.IGNORECASE | re.DOTALL):
                    result["status"] = "success"
                    result["message"] = "Telnet connection established and login attempt appears successful."
                    exit_code = 0
                    # Send 'exit' to terminate session gracefully
                    try:
                        process.stdin.write("exit\n")
                        process.stdin.flush()
                        time.sleep(1) # Give time for exit to process
                        process.wait(timeout=2) # Wait for process to terminate cleanly
                    except (BrokenPipeError, subprocess.TimeoutExpired):
                        pass # Ignore if pipe is already closed or it doesn't exit gracefully
                else:
                    if re.search(r'(failed|denied|incorrect|invalid)', output_buffer, re.IGNORECASE | re.DOTALL):
                        result["error"] = "Login attempt failed: Detected 'failed', 'denied' or similar in output."
                    else:
                        result["error"] = "Login attempt completed, but successful login prompt not detected."
                    exit_code = 1
            else:
                result["error"] = "Password prompt not found in output."
                exit_code = 1
        else:
            result["error"] = "Initial login/username prompt not found in output."
            exit_code = 1

    except FileNotFoundError:
        result["error"] = "Telnet client command not found. Please ensure Telnet client is installed on the system (e.g., `apt-get install telnet` on Debian/Ubuntu)."
        exit_code = 1
    except subprocess.TimeoutExpired:
        result["error"] = "Telnet process timed out before completion."
        exit_code = 1
    except Exception as e:
        # Catch any other unexpected errors during the process
        if not result.get("error"): # If a specific error wasn't set earlier
            result["error"] = f"An unexpected error occurred: {str(e)}"
        exit_code = 1
    finally:
        # Always ensure the accumulated output is included in the result
        result["output"] = output_buffer
        # Ensure the Telnet process is terminated if it's still running
        if process and process.poll() is None:
            try:
                # Attempt to gracefully exit, then kill if it doesn't
                process.stdin.write("exit\n")
                process.stdin.flush()
                process.wait(timeout=2)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                pass  # Ignore if pipe is already closed or it doesn't exit gracefully
            finally:
                if process.poll() is None:
                    process.kill()  # Force kill if still running

        # Print the JSON result to stdout
        print(json.dumps(result, indent=2))
        # Exit with the appropriate status code
        sys.exit(exit_code)

if __name__ == "__main__":
    main()