"""
SNMP Device Detection Service

Provides intelligent device detection using SNMP OID queries to identify
device vendors, models, platforms, and optimal plugin recommendations.
"""

import asyncio
import logging
import re
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import paramiko
# SNMP library imports
try:
    from pysnmp.hlapi.asyncio import *
    SNMP_AVAILABLE = True
except ImportError:
    SNMP_AVAILABLE = False

logger = logging.getLogger(__name__)

# Removed DeviceType enum - using platform strings instead for simplicity

@dataclass
class SNMPResult:
    """SNMP query result"""
    oid: str
    value: str
    success: bool
    error: Optional[str] = None

@dataclass
class DeviceDetectionResult:
    """Enhanced device detection result"""
    device_id: str
    detection_method: str = "static"
    vendor: str = "Unknown"
    model: str = "Unknown"
    platform: str = "unknown"
    os_version: str = "Unknown"
    snmp_enabled: bool = False
    optimal_plugins: List[str] = field(default_factory=list)
    raw_snmp_data: Dict[str, str] = field(default_factory=dict)
    detection_time: float = 0.0

class SNMPDetector:
    """SNMP-based device detection"""
    
    # Standard SNMP OIDs for device detection
    OIDS = {
        'sysDescr': '1.3.6.1.2.1.1.1.0',      # System description
        'sysObjectID': '1.3.6.1.2.1.1.2.0',   # System object identifier
        'sysName': '1.3.6.1.2.1.1.5.0',       # System name
        'sysContact': '1.3.6.1.2.1.1.4.0',    # System contact
        'sysLocation': '1.3.6.1.2.1.1.6.0',   # System location
        'ipForwarding': '1.3.6.1.2.1.4.1.0',  # IP forwarding status (1=router, 2=switch)
    }
    
    # Cisco enterprise OIDs and patterns
    CISCO_PATTERNS = [
        r'Cisco\s+(IOS|NX-OS|ASA)',
        r'Cisco\s+Internetwork\s+Operating\s+System',
        r'cisco',
        r'IOS.*Software',
    ]
    
    # Linux/Unix patterns
    LINUX_PATTERNS = [
        r'Linux',
        r'Ubuntu',
        r'Red\s+Hat',
        r'CentOS',
        r'SUSE',
        r'Debian',
        r'Net-SNMP',
    ]
    
    # Windows patterns  
    WINDOWS_PATTERNS = [
        r'Windows',
        r'Microsoft',
        r'Windows\s+Server',
    ]
    
    def __init__(self, community: str = "public", timeout: int = 3, retries: int = 1):
        """Initialize SNMP detector"""
        self.community = community
        self.timeout = timeout
        self.retries = retries
        self.snmp_available = SNMP_AVAILABLE
        
        if not self.snmp_available:
            logger.warning("PySNMP not available - SNMP detection disabled")

    async def detect_device(self, device_id: str, ip_address: str, device_context: Optional[Dict[str, Any]] = None) -> DeviceDetectionResult:
        """Detect device using SNMP with fallback to static detection"""
        import time
        start_time = time.time()
        
        result = DeviceDetectionResult(device_id=device_id)
        
        if not self.snmp_available:
            logger.debug(f"SNMP not available for {device_id} - using static detection")
            result.detection_time = time.time() - start_time
            return self._static_detection(result, ip_address, device_context)
        
        try:
            # Perform SNMP queries
            snmp_data = await self._query_snmp_oids(ip_address)

            # Check if we got any meaningful SNMP data
            successful_queries = [data for data in snmp_data.values() if data.success and data.value]
            
            if successful_queries:
                result.snmp_enabled = True
                result.detection_method = "snmp"
                result.raw_snmp_data = {oid: data.value for oid, data in snmp_data.items() if data.success}
                
                # Parse SNMP results
                result = await self._parse_snmp_data(result, snmp_data)
                
                logger.info(f"SNMP detection successful for {device_id}: {result.vendor} {result.model}")
            else:
                logger.warning(f"SNMP detection failed for {device_id} - using static fallback")
                result = self._static_detection(result, ip_address, device_context)
                
        except Exception as e:
            logger.error(f"SNMP detection error for {device_id}: {e}")
            result = self._static_detection(result, ip_address, device_context)
        
        result.detection_time = time.time() - start_time
        return result

    async def _query_snmp_oids(self, ip_address: str) -> Dict[str, SNMPResult]:
        """Query multiple SNMP OIDs in parallel"""
        if not self.snmp_available:
            return {}
        
        tasks = []
        for oid_name, oid in self.OIDS.items():
            task = self._query_single_oid(ip_address, oid_name, oid)
            tasks.append(task)
        
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            snmp_data = {}
            for i, result in enumerate(results):
                oid_name = list(self.OIDS.keys())[i]
                if isinstance(result, Exception):
                    snmp_data[oid_name] = SNMPResult(self.OIDS[oid_name], "", False, str(result))
                else:
                    snmp_data[oid_name] = result
            
            return snmp_data
            
        except Exception as e:
            logger.error(f"SNMP batch query failed: {e}")
            return {}

    async def _query_single_oid(self, ip_address: str, oid_name: str, oid: str) -> SNMPResult:
        """Query a single SNMP OID"""
        try:
            errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
                SnmpEngine(),
                CommunityData(self.community),
                await UdpTransportTarget.create((ip_address, 161)),
                ContextData(),
                ObjectType(ObjectIdentity(oid))
            )
            
            if errorIndication:
                return SNMPResult(oid, "", False, str(errorIndication))
            elif errorStatus:
                return SNMPResult(oid, "", False, f"{errorStatus} at {errorIndex}")
            else:
                # Extract value from varBinds
                if varBinds:
                    value = str(varBinds[0][1])
                    return SNMPResult(oid, value, True)
                else:
                    return SNMPResult(oid, "", False, "No data returned")
                    
        except Exception as e:
            return SNMPResult(oid, "", False, str(e))

    async def _parse_snmp_data(self, result: DeviceDetectionResult, snmp_data: Dict[str, SNMPResult]) -> DeviceDetectionResult:
        """Parse SNMP data to extract device information"""
        
        # Get sysDescr for primary analysis
        sys_descr = ""
        if 'sysDescr' in snmp_data and snmp_data['sysDescr'].success:
            sys_descr = snmp_data['sysDescr'].value
            
        # Get system name
        if 'sysName' in snmp_data and snmp_data['sysName'].success:
            result.raw_snmp_data['hostname'] = snmp_data['sysName'].value
        
        # Get ObjectID for model determination
        sys_object_id = ""
        if 'sysObjectID' in snmp_data and snmp_data['sysObjectID'].success:
            sys_object_id = snmp_data['sysObjectID'].value
        
        # Get ipForwarding for router/switch determination
        ip_forwarding = ""
        if 'ipForwarding' in snmp_data and snmp_data['ipForwarding'].success:
            ip_forwarding = snmp_data['ipForwarding'].value
        
        # Detect device vendor and basic info from sysDescr
        if sys_descr:
            result = self._analyze_sys_descr(result, sys_descr)
            
        # Use ipForwarding to determine router vs switch (most reliable)
        if ip_forwarding:
            result = self._analyze_ip_forwarding(result, ip_forwarding)
        
        # Determine optimal plugins based on platform
        result.optimal_plugins = self._get_optimal_plugins(result.platform)
        
        return result

    def _analyze_ip_forwarding(self, result: DeviceDetectionResult, ip_forwarding: str) -> DeviceDetectionResult:
        """Analyze ipForwarding to determine if device is router or switch"""
        try:
            forwarding_value = int(ip_forwarding.strip())
            
            if forwarding_value == 1:
                # IP forwarding enabled = Router
                result.platform = "cisco_ios_router"
                logger.info("Detected as router via ipForwarding=1")
            elif forwarding_value == 2:
                # IP forwarding disabled = Switch/L2 device  
                result.platform = "cisco_ios_switch"
                logger.info("Detected as switch via ipForwarding=2")
            else:
                logger.warning(f"Unknown ipForwarding value: {forwarding_value}")
                
        except (ValueError, AttributeError) as e:
            logger.warning(f"Could not parse ipForwarding value '{ip_forwarding}': {e}")
            
        return result

    def _analyze_sys_descr(self, result: DeviceDetectionResult, sys_descr: str) -> DeviceDetectionResult:
        """Analyze system description to determine device details"""
        
        # Check for Cisco devices
        for pattern in self.CISCO_PATTERNS:
            if re.search(pattern, sys_descr, re.IGNORECASE):
                result.vendor = "Cisco"
                result.platform = "cisco_ios"
                
                # Parse specific Cisco information
                result = self._parse_cisco_device(result, sys_descr)
                return result
        
        # Check for Linux devices
        for pattern in self.LINUX_PATTERNS:
            if re.search(pattern, sys_descr, re.IGNORECASE):
                result.vendor = "Linux"
                result.platform = "linux"
                
                # Parse Linux version info
                result = self._parse_linux_device(result, sys_descr)
                return result
        
        # Check for Windows devices
        for pattern in self.WINDOWS_PATTERNS:
            if re.search(pattern, sys_descr, re.IGNORECASE):
                result.vendor = "Microsoft"
                result.platform = "windows"
                return result
        
        # Generic network device fallback
        result.platform = "generic"
        return result

    def _parse_cisco_device(self, result: DeviceDetectionResult, sys_descr: str) -> DeviceDetectionResult:
        """Parse Cisco-specific device information"""
        
        # Extract model from common Cisco patterns
        # Example: "Cisco IOS Software, C2900 Software (C2900-UNIVERSALK9-M), Version 15.2(4)M3"
        model_match = re.search(r'(?:Software,\s+|IOS.*?)([A-Z]\d+[A-Z]*)', sys_descr)
        if model_match:
            result.model = model_match.group(1)
        
        # Extract version
        version_match = re.search(r'Version\s+([\d\.\(\):]+)', sys_descr)
        if version_match:
            result.os_version = version_match.group(1)
        
        # Note: device type determination now handled by ipForwarding analysis
        
        return result

    def _parse_linux_device(self, result: DeviceDetectionResult, sys_descr: str) -> DeviceDetectionResult:
        """Parse Linux-specific device information"""
        
        # Extract Linux distribution
        if 'Ubuntu' in sys_descr:
            result.model = "Ubuntu"
        elif 'Red Hat' in sys_descr:
            result.model = "Red Hat"
        elif 'CentOS' in sys_descr:
            result.model = "CentOS"
        else:
            result.model = "Linux"
        
        # Extract version if available
        version_match = re.search(r'(\d+\.\d+[\.\d]*)', sys_descr)
        if version_match:
            result.os_version = version_match.group(1)
        
        return result

    def _get_optimal_plugins(self, platform: str) -> List[str]:
        """Determine optimal plugins based on platform"""
        
        plugin_mapping = {
            "cisco_ios_router": ["ping", "command"],
            "cisco_ios_switch": ["ping", "command"],
            "cisco_ios": ["ping", "command"],  # fallback for generic cisco
            "linux": ["command", "ping"],
            "windows": ["ping", "command"],
            "generic": ["ping", "command"],
            "unknown": ["ping", "command"]
        }
        
        return plugin_mapping.get(platform, ["ping", "command"])

    def _static_detection(self, result: DeviceDetectionResult, ip_address: str, device_context: Optional[Dict[str, Any]] = None) -> DeviceDetectionResult:
        """Enhanced static detection method with SSH-based fallback"""
        result.detection_method = "static"
        
        # Try SSH-based detection first
        ssh_result = self._try_ssh_detection(ip_address, device_context)
        if ssh_result:
            result.vendor = ssh_result.get('vendor', 'Unknown')
            result.model = ssh_result.get('model', 'Unknown')
            result.platform = ssh_result.get('platform', 'generic')
            result.os_version = ssh_result.get('os_version', 'Unknown')
            result.optimal_plugins = self._get_optimal_plugins(result.platform)
            result.raw_snmp_data = ssh_result.get('raw_data', {})
        else:
            # Use device context or IP-based heuristics as final fallback
            if device_context:
                # Use device context data if available
                result.platform = device_context.get('platform', 'generic')
                if result.platform.startswith('cisco'):
                    result.vendor = "Cisco"
                    result.optimal_plugins = ["ping", "command"]
                elif result.platform == 'linux':
                    result.vendor = "Linux"
                    result.optimal_plugins = ["command", "ping"]
                else:
                    result.vendor = device_context.get('vendor', 'Unknown')
                    result.optimal_plugins = ["ping", "command"]
            else:
                # Generic fallback when no device context available
                result.platform = "generic"
                result.optimal_plugins = ["ping", "command"]
        
        return result

    def _try_ssh_detection(self, ip_address: str, device_context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Try to detect device via SSH commands (synchronous)"""
        import paramiko
        import socket
        
        # Get credentials from device context
        credentials = []
        if device_context and 'credentials' in device_context:
            # Use credentials from device context
            creds = device_context['credentials']
            username = creds.get('username')
            password = creds.get('password')
            if username and password:
                credentials.append((username, password))
        
        # If no credentials provided, SSH detection cannot proceed
        if not credentials:
            logger.debug(f"No SSH credentials provided for {ip_address} - skipping SSH detection")
            return None
        
        for username, password in credentials:
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(
                    hostname=ip_address,
                    username=username,
                    password=password,
                    timeout=3,
                    banner_timeout=3,
                    auth_timeout=3
                )
                
                # Try to determine device type
                device_info = self._detect_via_ssh_commands(ssh)
                ssh.close()
                
                if device_info:
                    device_info['raw_data'] = {'ssh_detection': 'success', 'credentials': f'{username}@{ip_address}'}
                    return device_info
                    
            except (paramiko.AuthenticationException, paramiko.SSHException, socket.timeout, socket.error):
                continue
            except Exception as e:
                logger.debug(f"SSH detection error for {ip_address}: {e}")
                continue
        
        return None

    def _detect_via_ssh_commands(self, ssh: 'paramiko.SSHClient') -> Optional[Dict[str, Any]]:
        """Detect device type via SSH commands"""
        try:
            # Try Cisco IOS detection
            stdin, stdout, stderr = ssh.exec_command('show version', timeout=5)
            output = stdout.read().decode('utf-8', errors='ignore')
            
            if 'Cisco IOS' in output or 'Cisco Internetwork' in output:
                # Parse Cisco device info
                vendor = "Cisco"
                platform = "cisco_ios"
                device_type = "cisco_router"
                model = "Unknown"
                os_version = "Unknown"
                
                # Extract model
                import re
                model_match = re.search(r'cisco\s+(\w+)', output, re.IGNORECASE)
                if model_match:
                    model = model_match.group(1)
                
                # Extract version
                version_match = re.search(r'Version\s+([\d\.\(\)A-Za-z]+)', output)
                if version_match:
                    os_version = version_match.group(1)
                
                return {
                    'vendor': vendor,
                    'model': model,
                    'platform': platform,
                    'os_version': os_version
                }
                
        except Exception:
            pass
        
        try:
            # Try Linux detection
            stdin, stdout, stderr = ssh.exec_command('uname -a', timeout=5)
            output = stdout.read().decode('utf-8', errors='ignore')
            
            if 'Linux' in output:
                # Parse Linux info
                vendor = "Linux"
                platform = "linux"
                model = "Generic"
                os_version = "Unknown"
                
                # Try to get more specific info
                try:
                    stdin, stdout, stderr = ssh.exec_command('lsb_release -d', timeout=3)
                    distro_output = stdout.read().decode('utf-8', errors='ignore')
                    if 'Ubuntu' in distro_output:
                        model = "Ubuntu"
                    elif 'CentOS' in distro_output:
                        model = "CentOS"
                except Exception:
                    pass
                
                # Extract version
                import re
                version_match = re.search(r'(\d+\.\d+[\.\d]*)', output)
                if version_match:
                    os_version = version_match.group(1)
                
                return {
                    'vendor': vendor,
                    'model': model,
                    'platform': platform,
                    'os_version': os_version
                }
                
        except Exception:
            pass
        
        return None

    async def detect_multiple_devices(self, devices: Dict[str, str], devices_context: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, DeviceDetectionResult]:
        """Detect multiple devices in parallel"""
        tasks = []
        
        for device_id, ip_address in devices.items():
            device_context = devices_context.get(device_id) if devices_context else None
            task = self.detect_device(device_id, ip_address, device_context)
            tasks.append(task)
        
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            detection_results = {}
            for i, result in enumerate(results):
                device_id = list(devices.keys())[i]
                if isinstance(result, Exception):
                    logger.error(f"Device detection failed for {device_id}: {result}")
                    # Create minimal result for failed detection
                    detection_results[device_id] = DeviceDetectionResult(
                        device_id=device_id,
                        detection_method="failed",
                        optimal_plugins=["ping", "command"]
                    )
                else:
                    detection_results[device_id] = result
            
            return detection_results
            
        except Exception as e:
            logger.error(f"Batch device detection failed: {e}")
            return {}


class DeviceDetectionService:
    """High-level device detection service"""
    
    def __init__(self, snmp_community: str = "public", snmp_timeout: int = 3):
        """Initialize detection service"""
        self.snmp_detector = SNMPDetector(community=snmp_community, timeout=snmp_timeout)
    
    async def enhanced_detect_devices(self, devices: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Enhanced device detection for integration with SimpleGradingService"""
        
        # Convert device list to IP mapping and context
        device_mapping = {}
        devices_context = {}
        for device in devices:
            device_id = device.get('id')
            ip_address = device.get('ip_address')
            if device_id and ip_address:
                device_mapping[device_id] = ip_address
                devices_context[device_id] = device
        
        if not device_mapping:
            logger.warning("No valid devices provided for detection")
            return {}
        # Perform detection
        logger.info(f"Starting SNMP detection for {len(device_mapping)} devices")
        detection_results = await self.snmp_detector.detect_multiple_devices(device_mapping, devices_context)
        
        # Convert to expected format
        enhanced_results = {}
        for device_id, result in detection_results.items():
            enhanced_results[device_id] = {
                "detection_method": result.detection_method,
                "vendor": result.vendor,
                "model": result.model,
                "platform": result.platform,
                "device_type": "unknown",
                "os_version": result.os_version,
                "snmp_enabled": result.snmp_enabled,
                "optimal_plugins": result.optimal_plugins,
                "detection_time": result.detection_time,
                "raw_data": result.raw_snmp_data
            }
        
        logger.info(f"SNMP detection completed: {sum(1 for r in detection_results.values() if r.snmp_enabled)} devices detected via SNMP")
        return enhanced_results