"""
IPv6 Utilities for network grading

Provides functions for IPv6 address normalization, validation, and comparison.
Supports full, compressed, and mixed IPv4/IPv6 formats.
"""

import re
import ipaddress
from typing import Optional, Tuple


def normalize_ipv6(address: str) -> Optional[str]:
    """
    Normalize an IPv6 address to its full expanded form.
    Removes prefix length if present, handles compressed notation.
    
    Args:
        address: IPv6 address string (e.g., "2001:db8::1", "2001:db8::1/64")
        
    Returns:
        Normalized full IPv6 address or None if invalid
        
    Examples:
        "2001:db8::1" -> "2001:0db8:0000:0000:0000:0000:0000:0001"
        "::1" -> "0000:0000:0000:0000:0000:0000:0000:0001"
        "2001:db8::1/64" -> "2001:0db8:0000:0000:0000:0000:0000:0001"
    """
    if not address:
        return None
    
    try:
        # Remove prefix length if present
        addr_without_prefix = address.split('/')[0].strip()
        
        # Parse and expand using Python's ipaddress module
        ipv6_obj = ipaddress.IPv6Address(addr_without_prefix)
        
        # Return exploded (full) form
        return ipv6_obj.exploded
        
    except (ipaddress.AddressValueError, ValueError):
        return None


def normalize_ipv6_with_prefix(address: str) -> Optional[str]:
    """
    Normalize an IPv6 address while preserving prefix length.
    
    Args:
        address: IPv6 address with optional prefix (e.g., "2001:db8::1/64")
        
    Returns:
        Normalized address with prefix or None if invalid
        
    Examples:
        "2001:db8::1/64" -> "2001:0db8:0000:0000:0000:0000:0000:0001/64"
        "2001:db8::1" -> "2001:0db8:0000:0000:0000:0000:0000:0001"
    """
    if not address:
        return None
    
    try:
        parts = address.split('/')
        addr_part = parts[0].strip()
        
        ipv6_obj = ipaddress.IPv6Address(addr_part)
        normalized_addr = ipv6_obj.exploded
        
        # Preserve prefix if present
        if len(parts) > 1:
            prefix = parts[1].strip()
            return f"{normalized_addr}/{prefix}"
        
        return normalized_addr
        
    except (ipaddress.AddressValueError, ValueError):
        return None


def compare_ipv6(addr1: str, addr2: str) -> bool:
    """
    Compare two IPv6 addresses for equality.
    Handles different notations (compressed, full, with/without prefix).
    
    Args:
        addr1: First IPv6 address
        addr2: Second IPv6 address
        
    Returns:
        True if addresses are equal (ignoring prefix length differences)
    """
    norm1 = normalize_ipv6(addr1)
    norm2 = normalize_ipv6(addr2)
    
    if norm1 is None or norm2 is None:
        return False
    
    return norm1.lower() == norm2.lower()


def is_valid_ipv6(address: str) -> bool:
    """
    Check if a string is a valid IPv6 address.
    
    Args:
        address: String to validate
        
    Returns:
        True if valid IPv6 address
    """
    return normalize_ipv6(address) is not None


def is_link_local(address: str) -> bool:
    """
    Check if an IPv6 address is a link-local address (fe80::/10).
    
    Args:
        address: IPv6 address to check
        
    Returns:
        True if address is link-local
    """
    try:
        addr_without_prefix = address.split('/')[0].strip()
        ipv6_obj = ipaddress.IPv6Address(addr_without_prefix)
        return ipv6_obj.is_link_local
    except (ipaddress.AddressValueError, ValueError):
        return False


def compare_link_local(actual: str, expected: bool = True) -> Tuple[bool, str]:
    """
    Compare if an address is a link-local IPv6 address.
    
    Args:
        actual: The actual IPv6 address
        expected: Whether we expect it to be link-local (default True)
        
    Returns:
        (passed, message) tuple
    """
    if not is_valid_ipv6(actual):
        return False, f"Invalid IPv6 address: {actual}"
    
    is_ll = is_link_local(actual)
    
    if expected:
        if is_ll:
            return True, f"Address {actual} is a valid link-local address"
        else:
            return False, f"Expected link-local address (fe80::/10), got: {actual}"
    else:
        if not is_ll:
            return True, f"Address {actual} is not link-local (as expected)"
        else:
            return False, f"Expected non-link-local address, got link-local: {actual}"


def get_ipv6_prefix(address: str) -> Optional[str]:
    """
    Extract the network prefix from an IPv6 address with prefix length.
    
    Args:
        address: IPv6 address with prefix (e.g., "2001:db8::1/64")
        
    Returns:
        Network prefix or None
        
    Example:
        "2001:db8::1/64" -> "2001:0db8:0000:0000::"
    """
    try:
        network = ipaddress.IPv6Network(address, strict=False)
        return str(network.network_address)
    except (ipaddress.AddressValueError, ValueError):
        return None


def get_interface_identifier(address: str) -> Optional[str]:
    """
    Extract the interface identifier (last 64 bits) from an IPv6 address.
    
    Args:
        address: IPv6 address
        
    Returns:
        Interface identifier as hex string or None
    """
    normalized = normalize_ipv6(address)
    if not normalized:
        return None
    
    # Get last 4 groups (64 bits)
    groups = normalized.split(':')
    return ':'.join(groups[4:])
