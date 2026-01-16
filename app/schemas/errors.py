"""
Grading Error Types - Structured error handling for grading services

This module provides structured error types that ensure user-facing error messages
are safe and user-friendly, while internal details are preserved for logging.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional


class GradingErrorType(str, Enum):
    """Categorized error types for grading operations"""
    CONNECTION_TIMEOUT = "connection_timeout"
    AUTH_FAILED = "auth_failed"
    CONNECTION_REFUSED = "connection_refused"
    HOST_UNREACHABLE = "host_unreachable"
    DNS_ERROR = "dns_error"
    SSH_KEY_ERROR = "ssh_key_error"
    COMMAND_TIMEOUT = "command_timeout"
    DEVICE_ERROR = "device_error"
    UNKNOWN_ERROR = "unknown_error"


# User-friendly error messages for each error type
ERROR_MESSAGES = {
    GradingErrorType.CONNECTION_TIMEOUT: (
        "Connection timeout: The device did not respond within the expected time. "
        "This may indicate the device is unreachable, busy, or the command took too long to execute."
    ),
    GradingErrorType.AUTH_FAILED: (
        "Authentication failed: Could not authenticate with the device. "
        "Please verify the credentials are correct."
    ),
    GradingErrorType.CONNECTION_REFUSED: (
        "Connection refused: The device actively refused the connection. "
        "Please verify the device is reachable and the service is running on the expected port."
    ),
    GradingErrorType.HOST_UNREACHABLE: (
        "Network error: The device is unreachable. Please verify network connectivity."
    ),
    GradingErrorType.DNS_ERROR: (
        "DNS error: Could not resolve the device hostname. "
        "Please verify the hostname is correct."
    ),
    GradingErrorType.SSH_KEY_ERROR: (
        "SSH key verification failed: Could not verify the device's SSH host key."
    ),
    GradingErrorType.COMMAND_TIMEOUT: (
        "Command timeout: The command took too long to execute on the device."
    ),
    GradingErrorType.DEVICE_ERROR: (
        "Device error: The device returned an error during task execution."
    ),
    GradingErrorType.UNKNOWN_ERROR: (
        "An unexpected error occurred during task execution. "
        "Please check the device connectivity and configuration."
    ),
}


@dataclass
class GradingError:
    """
    Structured error information for grading operations.
    
    Attributes:
        error_type: Categorized error type
        user_message: Safe, user-friendly message for display/callback
        internal_details: Full error details for logging only (never sent to user)
    """
    error_type: GradingErrorType
    user_message: str
    internal_details: Optional[str] = None
    
    @classmethod
    def from_type(cls, error_type: GradingErrorType, internal_details: Optional[str] = None) -> "GradingError":
        """Create a GradingError from an error type with default message."""
        return cls(
            error_type=error_type,
            user_message=ERROR_MESSAGES.get(error_type, ERROR_MESSAGES[GradingErrorType.UNKNOWN_ERROR]),
            internal_details=internal_details
        )
