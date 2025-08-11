#!/usr/bin/env python3
"""
Test script for the new data parsing approach
"""

import sys
import os
sys.path.append('.')

from app.services.data_parser import DataParser

def test_linux_ping_parsing():
    """Test Linux ping output parsing"""
    print("🧪 Testing Linux Ping Parsing")
    print("-" * 40)
    
    parser = DataParser()
    
    # Mock Linux ping output (successful)
    raw_data = {
        'test_type': 'ping',
        'target': '8.8.8.8',
        'device_type': 'linux',
        'raw_result': {
            'stdout': '''PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.
64 bytes from 8.8.8.8: icmp_seq=1 ttl=118 time=25.2 ms
64 bytes from 8.8.8.8: icmp_seq=2 ttl=118 time=24.8 ms
64 bytes from 8.8.8.8: icmp_seq=3 ttl=118 time=25.1 ms

--- 8.8.8.8 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 2003ms
rtt min/avg/max/mdev = 24.8/25.0/25.2/0.2 ms''',
            'rc': 0,
            'failed': False
        }
    }
    
    parsed = parser.parse_raw_data(raw_data)
    
    print("📊 Parsed Results:")
    for key, value in parsed.items():
        if key != 'raw_output':  # Skip raw output for cleaner display
            print(f"  {key}: {value}")
    
    print(f"\n✅ Success Rate: {parsed['success_rate']}%")
    print(f"📦 Packets: {parsed['packets_received']}/{parsed['packets_sent']}")
    print(f"⏱️  Average RTT: {parsed['avg_rtt']}ms")

def test_network_ping_parsing():
    """Test network device ping output parsing"""
    print("\n🧪 Testing Network Device Ping Parsing")
    print("-" * 40)
    
    parser = DataParser()
    
    # Mock Cisco ping output
    raw_data = {
        'test_type': 'ping',
        'target': '8.8.8.8',
        'device_type': 'network',
        'raw_result': {
            'stdout': '''Type escape sequence to abort.
Sending 5, 100-byte ICMP Echos to 8.8.8.8, timeout is 2 seconds:
!!!!!
Success rate is 100 percent (5/5), round-trip min/avg/max = 1/2/4 ms''',
            'failed': False,
            'dest': '8.8.8.8'
        }
    }
    
    parsed = parser.parse_raw_data(raw_data)
    
    print("📊 Parsed Results:")
    for key, value in parsed.items():
        if key != 'raw_output':
            print(f"  {key}: {value}")

def test_failed_ping_parsing():
    """Test failed ping parsing"""
    print("\n🧪 Testing Failed Ping Parsing")
    print("-" * 40)
    
    parser = DataParser()
    
    # Mock failed Linux ping
    raw_data = {
        'test_type': 'ping',
        'target': '192.168.999.999',
        'device_type': 'linux',
        'raw_result': {
            'stdout': '''PING 192.168.999.999 (192.168.999.999) 56(84) bytes of data.

--- 192.168.999.999 ping statistics ---
3 packets transmitted, 0 received, 100% packet loss, time 2000ms''',
            'rc': 1,
            'failed': True
        }
    }
    
    parsed = parser.parse_raw_data(raw_data)
    
    print("📊 Parsed Results:")
    for key, value in parsed.items():
        if key != 'raw_output':
            print(f"  {key}: {value}")

def test_service_parsing():
    """Test service status parsing"""
    print("\n🧪 Testing Service Status Parsing")
    print("-" * 40)
    
    parser = DataParser()
    
    # Mock service check output
    raw_data = {
        'test_type': 'service',
        'device_type': 'linux',
        'raw_result': {
            'stdout': 'active',
            'rc': 0,
            'failed': False
        }
    }
    
    parsed = parser.parse_raw_data(raw_data)
    
    print("📊 Parsed Results:")
    for key, value in parsed.items():
        if key != 'raw_output':
            print(f"  {key}: {value}")

if __name__ == "__main__":
    print("🚀 Data Parser Test Suite")
    print("=" * 50)
    
    try:
        test_linux_ping_parsing()
        test_network_ping_parsing()
        test_failed_ping_parsing()
        test_service_parsing()
        
        print("\n" + "=" * 50)
        print("✅ All parsing tests completed successfully!")
        print("\n💡 Benefits of the new approach:")
        print("   • Templates are simple and focused on data collection")
        print("   • Python handles all complex parsing logic")
        print("   • Easy to add new parsing methods (TextFSM, regex, etc.)")
        print("   • Instructors can easily customize templates")
        print("   • Separation of concerns: Ansible collects, Python processes")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()