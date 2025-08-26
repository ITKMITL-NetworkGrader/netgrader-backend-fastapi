#!/usr/bin/env python3
"""
Test job for the GNS3 topology:
- Router (10.70.38.2) with VLANs 101/102
- Switch with VLAN configuration  
- Ubuntu1 (192.168.101.2/24) in VLAN 101
- Ubuntu2 (192.168.102.2/24) in VLAN 102
"""

import asyncio
import json
from app.services.simple_grading_service import SimpleGradingService
from app.schemas.models import GradingJob

# Test job matching your exact topology
TOPOLOGY_TEST_JOB = {
    "job_id": "topology-test-001",
    "student_id": "test_student",
    "lab_id": "vlan_connectivity_lab",
    "part": {
        "part_id": "part1",
        "title": "VLAN Connectivity and Inter-VLAN Routing Test",
        "play": {
            "play_id": "connectivity_tests",
            "ansible_tasks": [
                # Test 1: Router can ping Ubuntu1 (VLAN 101)
                {
                    "task_id": "router_to_ubuntu1",
                    "template_name": "network_ping",
                    "execution_device": "router",
                    "parameters": {
                        "target_ip": "192.168.101.2",
                        "ping_count": 3
                    },
                    "test_cases": [
                        {
                            "comparison_type": "success",
                            "expected_result": True
                        }
                    ],
                    "points": 10
                },
                
                # Test 2: Router can ping Ubuntu2 (VLAN 102)  
                {
                    "task_id": "router_to_ubuntu2",
                    "template_name": "network_ping",
                    "execution_device": "router",
                    "parameters": {
                        "target_ip": "192.168.102.2",
                        "ping_count": 3
                    },
                    "test_cases": [
                        {
                            "comparison_type": "success",
                            "expected_result": True
                        }
                    ],
                    "points": 10
                },
                
                # Test 3: Check router VLAN 101 interface status
                {
                    "task_id": "check_vlan101_interface",
                    "template_name": "network_ip_int",
                    "execution_device": "router",
                    "parameters": {
                        "interface": "GigabitEthernet0/1.101",
                        "expected_ip": "192.168.101.1",
                        "check_ip": True
                    },
                    "test_cases": [
                        {
                            "comparison_type": "equals",
                            "field": "interface_operational",
                            "expected_result": True
                        }
                    ],
                    "points": 10
                },
                
                # Test 4: Check router VLAN 102 interface status
                {
                    "task_id": "check_vlan102_interface", 
                    "template_name": "network_ip_int",
                    "execution_device": "router",
                    "parameters": {
                        "interface": "GigabitEthernet0/1.102",
                        "expected_ip": "192.168.102.1",
                        "check_ip": True
                    },
                    "test_cases": [
                        {
                            "comparison_type": "equals",
                            "field": "interface_operational", 
                            "expected_result": True
                        }
                    ],
                    "points": 10
                },
                
                # Test 5: Ubuntu1 can reach its gateway
                {
                    "task_id": "ubuntu1_to_gateway",
                    "template_name": "network_ping",
                    "execution_device": "ubuntu1",
                    "parameters": {
                        "target_ip": "192.168.101.1",
                        "ping_count": 3
                    },
                    "test_cases": [
                        {
                            "comparison_type": "success",
                            "expected_result": True
                        }
                    ],
                    "points": 10
                },
                
                # Test 6: Ubuntu2 can reach its gateway
                {
                    "task_id": "ubuntu2_to_gateway",
                    "template_name": "network_ping", 
                    "execution_device": "ubuntu2",
                    "parameters": {
                        "target_ip": "192.168.102.1",
                        "ping_count": 3
                    },
                    "test_cases": [
                        {
                            "comparison_type": "success",
                            "expected_result": True
                        }
                    ],
                    "points": 10
                },
                
                # Test 7: Inter-VLAN connectivity (Ubuntu1 to Ubuntu2)
                {
                    "task_id": "inter_vlan_connectivity",
                    "template_name": "network_ping",
                    "execution_device": "ubuntu1", 
                    "parameters": {
                        "target_ip": "192.168.102.2",
                        "ping_count": 3
                    },
                    "test_cases": [
                        {
                            "comparison_type": "success",
                            "expected_result": True
                        }
                    ],
                    "points": 15
                },
                
                # Test 8: SSH connectivity from Ubuntu1 to Ubuntu2
                {
                    "task_id": "ssh_inter_vlan",
                    "template_name": "linux_remote_ssh",
                    "execution_device": "ubuntu1",
                    "parameters": {
                        "target_ip": "192.168.102.2",
                        "ssh_user": "ubuntu",  # Adjust if different
                        "ssh_password": "ubuntu",  # Adjust if different
                    },
                    "test_cases": [
                        {
                            "comparison_type": "success",
                            "expected_result": True
                        }
                    ],
                    "points": 15
                },
                
                # Test 9: Internet connectivity from Ubuntu1
                {
                    "task_id": "ubuntu1_internet",
                    "template_name": "network_ping",
                    "execution_device": "ubuntu1",
                    "parameters": {
                        "target_ip": "8.8.8.8",
                        "ping_count": 3
                    },
                    "test_cases": [
                        {
                            "comparison_type": "success", 
                            "expected_result": True
                        }
                    ],
                    "points": 10
                }
            ]
        }
    },
    "devices": [
        {
            "id": "router",
            "ip_address": "10.70.38.2",  # Management IP
            "ansible_connection": "ssh",
            "credentials": {
                "ansible_user": "admin",
                "ansible_password": "cisco"  # Default from your config
            },
            "platform": "cisco_ios",
            "role": "direct"
        },
        {
            "id": "switch",
            "ip_address": "192.168.101.254",  # VLAN 101 SVI
            "ansible_connection": "ssh", 
            "credentials": {
                "ansible_user": "admin",
                "ansible_password": "cisco"
            },
            "platform": "cisco_ios",
            "role": "direct"
        },
        {
            "id": "ubuntu1",
            "ip_address": "192.168.101.2",
            "ansible_connection": "ssh",
            "credentials": {
                "ansible_user": "ubuntu",  # Adjust if different
                "ansible_password": "ubuntu"  # Adjust if different  
            },
            "platform": "linux",
            "role": "direct"
        },
        {
            "id": "ubuntu2", 
            "ip_address": "192.168.102.2",
            "ansible_connection": "ssh",
            "credentials": {
                "ansible_user": "ubuntu",  # Adjust if different
                "ansible_password": "ubuntu"  # Adjust if different
            },
            "platform": "linux", 
            "role": "direct"
        }
    ],
    "ip_mappings": {
        "router_mgmt": "10.70.38.2",
        "router_vlan101": "192.168.101.1",
        "router_vlan102": "192.168.102.1", 
        "switch_mgmt": "192.168.101.254",
        "ubuntu1_ip": "192.168.101.2",
        "ubuntu2_ip": "192.168.102.2",
        "gateway_vlan101": "192.168.101.1",
        "gateway_vlan102": "192.168.102.1"
    },
    "callback_url": "http://10.50.37.43:4000/v0/grading"  # Set to your callback URL if needed
}

async def test_topology():
    """Test the complete topology"""
    print("🚀 Starting Topology Test...")
    print("📋 Testing:")
    print("   - Router (10.70.38.2)")
    print("   - Switch (192.168.101.254)")  
    print("   - Ubuntu1 (192.168.101.2) in VLAN 101")
    print("   - Ubuntu2 (192.168.102.2) in VLAN 102")
    print()
    
    # Initialize simple grading service
    grading_service = SimpleGradingService()
    await grading_service.initialize()
    print("✅ Simple Grading Service initialized")
    
    # Create job
    job = GradingJob(**TOPOLOGY_TEST_JOB)
    
    # Test enhanced device detection
    print("\n🔍 Testing enhanced device detection...")
    try:
        detection_results = await grading_service.detect_devices(job)
        print(f"   📊 Detection Summary:")
        
        snmp_devices = [d for d in detection_results.values() if d.get('detection_method') == 'snmp']
        static_devices = [d for d in detection_results.values() if d.get('detection_method') == 'static']
        
        print(f"   └─ SNMP Detection: {len(snmp_devices)} devices")
        print(f"   └─ Static Detection: {len(static_devices)} devices")
        print()
        
        for device_id, result in detection_results.items():
            method_icon = "🌐" if result.get('detection_method') == 'snmp' else "📋"
            snmp_status = "✅" if result.get('snmp_enabled') else "❌"
            detection_time = result.get('detection_time', 0.0)
            
            print(f"   {method_icon} {device_id}:")
            print(f"      └─ Vendor: {result.get('vendor', 'Unknown')}")
            print(f"      └─ Model: {result.get('model', 'Unknown')}")
            print(f"      └─ Platform: {result.get('platform', 'unknown')}")
            print(f"      └─ OS Version: {result.get('os_version', 'Unknown')}")
            print(f"      └─ SNMP Enabled: {snmp_status}")
            print(f"      └─ Detection Time: {detection_time:.3f}s")
            print(f"      └─ Optimal Plugins: {', '.join(result.get('optimal_plugins', []))}")
            
            # Show raw SNMP data if available
            raw_data = result.get('raw_data', {})
            if raw_data:
                print(f"      └─ Raw SNMP Data:")
                for key, value in raw_data.items():
                    print(f"         • {key}: {value[:100]}{'...' if len(str(value)) > 100 else ''}")
            print()
            
    except Exception as e:
        print(f"⚠️ Enhanced device detection failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Test connectivity to all devices
    # print("\n🔌 Testing connectivity...")
    # try:
    #     connectivity = await grading_service.test_connectivity(job)
    #     for device_id, connected in connectivity.items():
    #         status = "✅ CONNECTED" if connected else "❌ FAILED"
    #         print(f"   {device_id}: {status}")
    # except Exception as e:
    #     print(f"⚠️ Connectivity test failed: {e}")
    
    # # Test job validation
    # print("\n📋 Validating job...")
    # validation = await grading_service.validate_job_payload(job)
    # if validation['valid']:
    #     print("✅ Job validation passed")
    # else:
    #     print("❌ Job validation failed:")
    #     for error in validation['errors']:
    #         print(f"   - {error}")
    #     return
    
    # # Run the actual grading
    # print(f"\n🎯 Running grading test ({len(job.part.play.ansible_tasks)} tasks)...")
    # try:
    #     result = await grading_service.process_grading_job(job)
        
    #     print(f"\n📊 GRADING RESULTS:")
    #     print(f"   Status: {result.status}")
    #     print(f"   Score: {result.total_points_earned}/{result.total_points_possible}")
    #     print(f"   Success Rate: {(result.total_points_earned/result.total_points_possible*100):.1f}%")
    #     print(f"   Execution Time: {result.total_execution_time:.2f}s")
        
    #     print(f"\n📝 Individual Test Results:")
    #     for test in result.test_results:
    #         status_emoji = "✅" if test.status == "passed" else ("⚠️" if test.status == "partial" else "❌")
    #         print(f"   {status_emoji} {test.test_name}: {test.status} ({test.points_earned}/{test.points_possible} pts)")
    #         if test.message:
    #             print(f"      └─ {test.message}")
        
    # except Exception as e:
    #     print(f"❌ Grading test failed: {e}")
    #     import traceback
    #     traceback.print_exc()

if __name__ == "__main__":
    print("🏗️ Topology Test Job for GNS3 Lab")
    print("📝 Before running, ensure:")
    print("   1. All devices are powered on and accessible")  
    print("   2. SSH credentials are correct in the job config")
    print("   3. NetGrader server can reach 10.70.38.2")
    print("   4. Ubuntu machines have SSH enabled")
    print()
    
    # Update credentials if needed before running
    asyncio.run(test_topology())