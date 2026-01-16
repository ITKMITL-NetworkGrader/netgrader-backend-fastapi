"""
Exception Handler - Classifies exceptions into structured GradingErrors

This module provides exception classification that maps specific exception types
to user-friendly error messages while preserving internal details for logging.
"""

import logging
import socket
from typing import TYPE_CHECKING

from app.schemas.errors import GradingError, GradingErrorType, ERROR_MESSAGES

logger = logging.getLogger(__name__)


def classify_exception(e: Exception) -> GradingError:
    """
    Classify an exception and return a structured GradingError.
    
    This function inspects the exception type and content to determine
    the appropriate error category and user-friendly message.
    
    Args:
        e: The exception to classify
        
    Returns:
        GradingError with appropriate error_type, user_message, and internal_details
    """
    error_str = str(e).lower()
    exception_type = type(e).__name__
    internal_details = f"{exception_type}: {str(e)}"
    
    # Try to import Netmiko exceptions (may not be available in all contexts)
    try:
        from netmiko.exceptions import (
            NetmikoTimeoutException,
            NetmikoAuthenticationException,
            ReadTimeout,
        )
        
        if isinstance(e, (NetmikoTimeoutException, ReadTimeout)):
            return GradingError.from_type(
                GradingErrorType.CONNECTION_TIMEOUT,
                internal_details=internal_details
            )
        
        if isinstance(e, NetmikoAuthenticationException):
            return GradingError.from_type(
                GradingErrorType.AUTH_FAILED,
                internal_details=internal_details
            )
    except ImportError:
        pass
    
    # Try to import Paramiko exceptions
    try:
        from paramiko.ssh_exception import (
            AuthenticationException,
            SSHException,
        )
        
        if isinstance(e, AuthenticationException):
            return GradingError.from_type(
                GradingErrorType.AUTH_FAILED,
                internal_details=internal_details
            )
        
        if isinstance(e, SSHException):
            # Check for specific SSH issues
            if "host key" in error_str:
                return GradingError.from_type(
                    GradingErrorType.SSH_KEY_ERROR,
                    internal_details=internal_details
                )
    except ImportError:
        pass
    
    # Socket exceptions
    if isinstance(e, socket.timeout):
        return GradingError.from_type(
            GradingErrorType.CONNECTION_TIMEOUT,
            internal_details=internal_details
        )
    
    if isinstance(e, ConnectionRefusedError):
        return GradingError.from_type(
            GradingErrorType.CONNECTION_REFUSED,
            internal_details=internal_details
        )
    
    if isinstance(e, OSError):
        # Check for network-related OS errors
        if "no route to host" in error_str or e.errno == 113:  # EHOSTUNREACH
            return GradingError.from_type(
                GradingErrorType.HOST_UNREACHABLE,
                internal_details=internal_details
            )
        if "connection refused" in error_str or e.errno == 111:  # ECONNREFUSED
            return GradingError.from_type(
                GradingErrorType.CONNECTION_REFUSED,
                internal_details=internal_details
            )
        if "name or service not known" in error_str:
            return GradingError.from_type(
                GradingErrorType.DNS_ERROR,
                internal_details=internal_details
            )
    
    # String-based fallback detection for wrapped exceptions
    # These patterns catch errors that may be wrapped in other exception types
    
    # Timeout patterns
    if any(pattern in error_str for pattern in [
        "readtimeout", "timed out", "timeout", "pattern not detected"
    ]):
        return GradingError.from_type(
            GradingErrorType.CONNECTION_TIMEOUT,
            internal_details=internal_details
        )
    
    # Authentication patterns
    if any(pattern in error_str for pattern in [
        "authentication", "permission denied", "access denied"
    ]):
        return GradingError.from_type(
            GradingErrorType.AUTH_FAILED,
            internal_details=internal_details
        )
    
    # Connection refused patterns
    if "connection refused" in error_str:
        return GradingError.from_type(
            GradingErrorType.CONNECTION_REFUSED,
            internal_details=internal_details
        )
    
    # Host unreachable patterns
    if any(pattern in error_str for pattern in [
        "no route to host", "host unreachable", "network unreachable"
    ]):
        return GradingError.from_type(
            GradingErrorType.HOST_UNREACHABLE,
            internal_details=internal_details
        )
    
    # DNS patterns
    if any(pattern in error_str for pattern in [
        "name or service not known", "could not resolve", "dns"
    ]):
        return GradingError.from_type(
            GradingErrorType.DNS_ERROR,
            internal_details=internal_details
        )
    
    # SSH key patterns
    if "host key" in error_str:
        return GradingError.from_type(
            GradingErrorType.SSH_KEY_ERROR,
            internal_details=internal_details
        )
    
    # Default: unknown error (never expose internal details in user message)
    logger.debug(f"Unclassified exception: {internal_details}")
    return GradingError.from_type(
        GradingErrorType.UNKNOWN_ERROR,
        internal_details=internal_details
    )
