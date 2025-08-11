"""
Data parsing service using TextFSM and other parsing methods
Handles raw Ansible output and converts it to structured data for scoring
"""

import re
import json
import logging
from typing import Dict, Any, Optional
# import textfsm
# from io import StringIO

logger = logging.getLogger(__name__)

class DataParser:
    """Service for parsing raw network command output into structured data"""
    
    def __init__(self):
        # TextFSM templates for common network commands
        self.textfsm_templates = {
            'ping_cisco': self._get_cisco_ping_template(),
            'ping_linux': self._get_linux_ping_template(),
            'show_ip_route': self._get_route_template(),
            'show_interfaces': self._get_interface_template()
        }
    
    def parse_raw_data(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse raw Ansible output into structured data
        
        Args:
            raw_data: Raw data from Ansible task result
            
        Returns:
            Structured data dictionary ready for scoring
        """
        test_type = raw_data.get('test_type', 'unknown')
        device_type = raw_data.get('device_type', 'unknown')
        raw_result = raw_data.get('raw_result', {})
        
        if test_type == 'ping':
            return self._parse_ping_data(raw_result, device_type)
        elif test_type == 'route':
            return self._parse_route_data(raw_result, device_type)
        elif test_type == 'interface':
            return self._parse_interface_data(raw_result, device_type)
        elif test_type == 'service':
            return self._parse_service_data(raw_result, device_type)
        else:
            logger.warning(f"Unknown test type: {test_type}")
            return self._parse_generic_data(raw_result)
    
    def _parse_ping_data(self, raw_result: Dict[str, Any], device_type: str) -> Dict[str, Any]:
        """Parse ping command output"""
        
        if device_type == 'network':
            # Parse Cisco/network device ping output
            return self._parse_network_ping(raw_result)
        else:
            # Parse Linux ping output
            return self._parse_linux_ping(raw_result)
    
    def _parse_network_ping(self, raw_result: Dict[str, Any]) -> Dict[str, Any]:
        """Parse network device ping output using TextFSM"""
        
        # Extract basic info from Ansible result
        failed = raw_result.get('failed', False)
        stdout = raw_result.get('stdout', '')
        
        if failed or not stdout:
            return {
                'target': raw_result.get('dest', 'unknown'),
                'packets_sent': 0,
                'packets_received': 0,
                'success_rate': 0,
                'avg_rtt': 0,
                'status': 'failed',
                'raw_output': str(raw_result)
            }
        
        # Use TextFSM to parse Cisco ping output (when available)
        # try:
        #     template = textfsm.TextFSM(StringIO(self.textfsm_templates['ping_cisco']))
        #     parsed_data = template.ParseText(stdout)
        #     
        #     if parsed_data:
        #         result = parsed_data[0]  # First (and usually only) result
        #         return {
        #             'target': result[0] if len(result) > 0 else 'unknown',
        #             'packets_sent': int(result[1]) if len(result) > 1 else 0,
        #             'packets_received': int(result[2]) if len(result) > 2 else 0,
        #             'success_rate': float(result[3]) if len(result) > 3 else 0,
        #             'avg_rtt': float(result[4]) if len(result) > 4 else 0,
        #             'status': 'success' if int(result[2]) > 0 else 'failed',
        #             'raw_output': stdout
        #         }
        # except Exception as e:
        #     logger.warning(f"TextFSM parsing failed for network ping: {e}")
        
        # Fallback to regex parsing
        return self._parse_network_ping_regex(stdout, raw_result)
    
    def _parse_linux_ping(self, raw_result: Dict[str, Any]) -> Dict[str, Any]:
        """Parse Linux ping output using TextFSM"""
        
        stdout = raw_result.get('stdout', '')
        rc = raw_result.get('rc', 1)
        
        if rc != 0 or not stdout:
            return {
                'target': 'unknown',
                'packets_sent': 0,
                'packets_received': 0,
                'success_rate': 0,
                'avg_rtt': 0,
                'status': 'failed',
                'raw_output': stdout
            }
        
        # Use TextFSM to parse Linux ping output (when available)
        # try:
        #     template = textfsm.TextFSM(StringIO(self.textfsm_templates['ping_linux']))
        #     parsed_data = template.ParseText(stdout)
        #     
        #     if parsed_data:
        #         result = parsed_data[0]
        #         packets_sent = int(result[1])
        #         packets_received = int(result[2])
        #         success_rate = (packets_received / packets_sent * 100) if packets_sent > 0 else 0
        #         
        #         return {
        #             'target': result[0],
        #             'packets_sent': packets_sent,
        #             'packets_received': packets_received,
        #             'success_rate': round(success_rate, 1),
        #             'avg_rtt': float(result[3]) if len(result) > 3 else 0,
        #             'status': 'success' if packets_received > 0 else 'failed',
        #             'raw_output': stdout
        #         }
        # except Exception as e:
        #     logger.warning(f"TextFSM parsing failed for Linux ping: {e}")
        
        # Fallback to regex parsing
        return self._parse_linux_ping_regex(stdout)
    
    def _parse_network_ping_regex(self, stdout: str, raw_result: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback regex parsing for network ping"""
        
        # Extract target from raw_result or stdout
        target = raw_result.get('dest', 'unknown')
        
        # Parse success rate from output like "Success rate is 100 percent (5/5)"
        success_match = re.search(r'Success rate is (\d+) percent \((\d+)/(\d+)\)', stdout)
        if success_match:
            success_rate = int(success_match.group(1))
            packets_received = int(success_match.group(2))
            packets_sent = int(success_match.group(3))
        else:
            success_rate = 0
            packets_received = 0
            packets_sent = 5  # Default for Cisco
        
        # Parse RTT from output like "round-trip min/avg/max = 1/2/4 ms"
        rtt_match = re.search(r'round-trip min/avg/max = \d+/(\d+)/\d+ ms', stdout)
        avg_rtt = float(rtt_match.group(1)) if rtt_match else 0
        
        return {
            'target': target,
            'packets_sent': packets_sent,
            'packets_received': packets_received,
            'success_rate': success_rate,
            'avg_rtt': avg_rtt,
            'status': 'success' if packets_received > 0 else 'failed',
            'raw_output': stdout
        }
    
    def _parse_linux_ping_regex(self, stdout: str) -> Dict[str, Any]:
        """Fallback regex parsing for Linux ping"""
        
        # Extract target from first line like "PING 8.8.8.8 (8.8.8.8)"
        target_match = re.search(r'PING ([^\s]+)', stdout)
        target = target_match.group(1) if target_match else 'unknown'
        
        # Extract statistics from line like "3 packets transmitted, 3 received, 0% packet loss"
        stats_match = re.search(r'(\d+) packets transmitted, (\d+) received, (\d+)% packet loss', stdout)
        if stats_match:
            packets_sent = int(stats_match.group(1))
            packets_received = int(stats_match.group(2))
            packet_loss = int(stats_match.group(3))
            success_rate = 100 - packet_loss
        else:
            packets_sent = 0
            packets_received = 0
            success_rate = 0
        
        # Extract RTT from line like "rtt min/avg/max/mdev = 24.8/25.0/25.2/0.2 ms"
        rtt_match = re.search(r'rtt min/avg/max/mdev = [0-9.]+/([0-9.]+)/[0-9.]+/[0-9.]+ ms', stdout)
        avg_rtt = float(rtt_match.group(1)) if rtt_match else 0
        
        return {
            'target': target,
            'packets_sent': packets_sent,
            'packets_received': packets_received,
            'success_rate': success_rate,
            'avg_rtt': avg_rtt,
            'status': 'success' if packets_received > 0 else 'failed',
            'raw_output': stdout
        }
    
    def _parse_route_data(self, raw_result: Dict[str, Any], device_type: str) -> Dict[str, Any]:
        """Parse routing table output"""
        stdout = raw_result.get('stdout', '')
        rc = raw_result.get('rc', 1)
        
        if rc != 0 or not stdout:
            return {
                'has_default_route': False,
                'route_count': 0,
                'routes': [],
                'raw_output': stdout
            }
        
        # Parse routing information
        routes = []
        has_default = False
        
        for line in stdout.split('\n'):
            line = line.strip()
            if not line:
                continue
                
            # Check for default route
            if 'default' in line.lower() or '0.0.0.0/0' in line:
                has_default = True
            
            # Collect route entries (basic parsing)
            if '/' in line and ('via' in line or 'dev' in line):
                routes.append(line)
        
        return {
            'has_default_route': has_default,
            'route_count': len(routes),
            'routes': routes,
            'raw_output': stdout
        }
    
    def _parse_interface_data(self, raw_result: Dict[str, Any], device_type: str) -> Dict[str, Any]:
        """Parse interface status output"""
        # Implementation for interface parsing
        return {'parsed': False, 'raw_output': str(raw_result)}
    
    def _parse_service_data(self, raw_result: Dict[str, Any], device_type: str) -> Dict[str, Any]:
        """Parse service status output"""
        stdout = raw_result.get('stdout', '')
        rc = raw_result.get('rc', 1)
        
        return {
            'service_active': rc == 0,
            'service_status': 'active' if rc == 0 else 'inactive',
            'raw_output': stdout
        }
    
    def _parse_generic_data(self, raw_result: Dict[str, Any]) -> Dict[str, Any]:
        """Generic parser for unknown data types"""
        return {
            'success': not raw_result.get('failed', False),
            'return_code': raw_result.get('rc', 0),
            'stdout': raw_result.get('stdout', ''),
            'stderr': raw_result.get('stderr', ''),
            'raw_output': str(raw_result)
        }
    
    def _get_cisco_ping_template(self) -> str:
        """TextFSM template for Cisco ping output"""
        return """
Value TARGET (\\S+)
Value SENT (\\d+)
Value RECEIVED (\\d+)
Value SUCCESS_RATE (\\d+)
Value AVG_RTT (\\d+)

Start
  ^Type escape sequence to abort.
  ^Sending ${SENT}, \\d+-byte ICMP Echos to ${TARGET}, timeout is \\d+ seconds:
  ^Success rate is ${SUCCESS_RATE} percent \\(${RECEIVED}/${SENT}\\), round-trip min/avg/max = \\d+/${AVG_RTT}/\\d+ ms -> Record
"""
    
    def _get_linux_ping_template(self) -> str:
        """TextFSM template for Linux ping output"""
        return """
Value TARGET (\\S+)
Value SENT (\\d+)
Value RECEIVED (\\d+)
Value AVG_RTT ([\\d.]+)

Start
  ^PING ${TARGET}
  ^${SENT} packets transmitted, ${RECEIVED} received, \\d+% packet loss, time \\d+ms
  ^rtt min/avg/max/mdev = [\\d.]+/${AVG_RTT}/[\\d.]+/[\\d.]+ ms -> Record
"""
    
    def _get_route_template(self) -> str:
        """TextFSM template for routing table"""
        return """
Value NETWORK (\\S+)
Value MASK (\\S+)
Value NEXT_HOP (\\S+)
Value INTERFACE (\\S+)

Start
  ^${NETWORK}/${MASK}\\s+${NEXT_HOP}\\s+${INTERFACE} -> Record
"""
    
    def _get_interface_template(self) -> str:
        """TextFSM template for interface status"""
        return """
Value INTERFACE (\\S+)
Value STATUS (\\S+)
Value PROTOCOL (\\S+)

Start
  ^${INTERFACE}\\s+is\\s+${STATUS},\\s+line\\s+protocol\\s+is\\s+${PROTOCOL} -> Record
"""