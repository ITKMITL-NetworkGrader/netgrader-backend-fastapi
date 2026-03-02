"""
Script Manager - Business logic for script storage management

Handles:
- Checking if scripts exist for given tasks
- Saving new scripts to the file system
- Executing scripts via subprocess
"""
import os
import subprocess
import logging
from pathlib import Path
import sys

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Base directory for script storage (relative to project root)
SCRIPT_STORAGE_DIR = Path(__file__).parent.parent.parent.parent / "script-storage"


def get_script_storage_dir() -> Path:
    """Get the script storage directory path. Can be overridden in the future."""
    return SCRIPT_STORAGE_DIR


# =============================================================================
# Script Path Resolution
# =============================================================================

def resolve_script_path(device_type: str, os_type: str, action: str) -> Path:
    """
    Resolve the expected script path for a given task.
    Pattern: script-storage/{device_type}/{os_type}/{action}.py
    """
    return get_script_storage_dir() / device_type / os_type / f"{action}.py"


def script_exists(device_type: str, os_type: str, action: str) -> bool:
    """Check if a script file exists for the given task parameters."""
    path = resolve_script_path(device_type, os_type, action)
    return path.is_file()


# =============================================================================
# Script Check
# =============================================================================

def check_scripts(tasks: list[dict]) -> list[dict]:
    """
    Check which tasks have scripts available.
    
    Args:
        tasks: List of task dicts with keys: id, action, device_type, os
    
    Returns:
        List of status dicts with: id, action, device_type, os, found, script_path
    """
    results = []
    for task in tasks:
        task_id = task.get("id", 0)
        action = task.get("action", "")
        device_type = task.get("device_type", "")
        os_type = task.get("os", "")

        path = resolve_script_path(device_type, os_type, action)
        found = path.is_file()

        results.append({
            "id": task_id,
            "action": action,
            "device_type": device_type,
            "os": os_type,
            "found": found,
            "script_path": str(path) if found else None
        })

        logger.info(
            f"[ScriptCheck] Task {task_id} ({action}) on {device_type}/{os_type}: "
            f"{'FOUND' if found else 'MISSING'}"
        )

    return results


# =============================================================================
# Script Save
# =============================================================================

def save_script(
    device_type: str,
    os_type: str,
    action: str,
    code: str,
    description: str | None = None
) -> dict:
    """
    Save a script to the file system.
    
    Args:
        device_type: e.g. "host", "network_device"
        os_type: e.g. "linux", "cisco"
        action: e.g. "ping", "show_interface"
        code: Python script content
        description: Optional description (added as comment header)
    
    Returns:
        dict with success, message, script_path
    """
    path = resolve_script_path(device_type, os_type, action)

    # Create directories if needed
    path.parent.mkdir(parents=True, exist_ok=True)

    # Add description header if provided
    content = code
    if description:
        header = f'"""\n{description}\n"""\n\n'
        if not code.startswith('"""'):
            content = header + code

    # Write script
    path.write_text(content, encoding="utf-8")

    logger.info(f"[ScriptSave] Saved script: {path}")

    return {
        "success": True,
        "message": f"Script saved: {device_type}/{os_type}/{action}.py",
        "script_path": str(path)
    }


# =============================================================================
# Script Execution
# =============================================================================

def execute_script(
    device_type: str,
    os_type: str,
    action: str,
    params: dict | None = None
) -> dict:
    """
    Execute a script via subprocess.
    
    The script is executed as: python {script_path} [--param_key param_value ...]
    Parameters are passed as command-line arguments.
    
    Args:
        device_type: e.g. "host", "network_device"
        os_type: e.g. "linux", "cisco"
        action: e.g. "ping"
        params: dict of parameters to pass to the script
    
    Returns:
        dict with success, output, error
    """
    path = resolve_script_path(device_type, os_type, action)

    if not path.is_file():
        return {
            "success": False,
            "output": None,
            "error": f"Script not found: {path}"
        }
    # แก้ไขให้ใช้ python ที่ถูกต้อง จาก venv 
    python_bin = sys.executable
    # Build command
    cmd = [python_bin, str(path)]
    if params:
        for key, value in params.items():
            cmd.extend([f"--{key}", str(value)])

    logger.info(f"[ScriptExec] Running: {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,  # 2 minute timeout
        cwd=str(path.parent)
    )

    success = result.returncode == 0
    output = result.stdout.strip() if result.stdout else None
    error = result.stderr.strip() if result.stderr else None

    logger.info(
        f"[ScriptExec] {action}: "
        f"{'SUCCESS' if success else 'FAILED'} "
        f"(exit code: {result.returncode})"
    )

    return {
        "success": success,
        "output": output,
        "error": error
    }
