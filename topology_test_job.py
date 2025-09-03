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
        "ansible_tasks": [
                # Group 1: Router Interface Configuration (All-or-Nothing)
                # Test 1: Check router VLAN 101 interface status
                # {
                #     "task_id": "check_vlan101_interface",
                #     "template_name": "network_ip_int",
                #     "execution_mode": "shared",
                #     "execution_device": "router",
                #     "group_id": "router_interfaces",
                #     "points": 8,
                #     "parameters": {
                #         "interface": "GigabitEthernet0/1.101",
                #         "expected_ip": "192.168.101.1",
                #         "check_ip": True
                #     },
                #     "test_cases": [
                #         {
                #             "comparison_type": "equals",
                #             "expected_result": True
                #         }
                #     ]
                # },
                
                # # Test 2: Check router VLAN 102 interface status
                # {
                #     "task_id": "check_vlan102_interface", 
                #     "template_name": "network_ip_int",
                #     "execution_mode": "shared",
                #     "execution_device": "router",
                #     "group_id": "router_interfaces",
                #     "parameters": {
                #         "interface": "GigabitEthernet0/1.102",
                #         "expected_ip": "192.168.102.1",
                #         "check_ip": True
                #     },
                #     "test_cases": [
                #         {
                #             "comparison_type": "equals",
                #             "field": "interface_operational", 
                #             "expected_result": True
                #         }
                #     ]
                # },
                
                # # Group 2: Basic Connectivity (All-or-Nothing) 
                # # Test 3: Router can ping Ubuntu1 (VLAN 101)
                # {
                #     "task_id": "router_to_ubuntu1",
                #     "template_name": "network_ping",
                #     "execution_device": "router",
                #     "group_id": "basic_connectivity",
                #     "parameters": {
                #         "target_ip": "192.168.101.2",
                #         "ping_count": 3
                #     },
                #     "test_cases": [
                #         {
                #             "comparison_type": "success",
                #             "expected_result": True
                #         }
                #     ]
                # },
                
                # # Test 4: Router can ping Ubuntu2 (VLAN 102)  
                # {
                #     "task_id": "router_to_ubuntu2",
                #     "template_name": "network_ping",
                #     "execution_device": "router",
                #     "group_id": "basic_connectivity",
                #     "parameters": {
                #         "target_ip": "192.168.102.2",
                #         "ping_count": 3
                #     },
                #     "test_cases": [
                #         {
                #             "comparison_type": "success",
                #             "expected_result": True
                #         }
                #     ]
                # },
                
                # # Group 3: Gateway Connectivity (Proportional)
                # # Test 5: Ubuntu1 can reach its gateway
                # {
                #     "task_id": "ubuntu1_to_gateway",
                #     "template_name": "network_ping",
                #     "execution_device": "ubuntu1",
                #     "group_id": "gateway_connectivity",
                #     "parameters": {
                #         "target_ip": "192.168.101.1",
                #         "ping_count": 3
                #     },
                #     "test_cases": [
                #         {
                #             "comparison_type": "success",
                #             "expected_result": True
                #         }
                #     ]
                # },
                
                # # Test 6: Ubuntu2 can reach its gateway
                # {
                #     "task_id": "ubuntu2_to_gateway",
                #     "template_name": "network_ping", 
                #     "execution_device": "ubuntu2",
                #     "group_id": "gateway_connectivity",
                #     "parameters": {
                #         "target_ip": "192.168.102.1",
                #         "ping_count": 3
                #     },
                #     "test_cases": [
                #         {
                #             "comparison_type": "success",
                #             "expected_result": True
                #         }
                #     ]
                # },
                
                # # Group 4: Advanced Services (Proportional) 
                # # Test 7: Inter-VLAN connectivity (Ubuntu1 to Ubuntu2)
                # {
                #     "task_id": "inter_vlan_connectivity",
                #     "template_name": "network_ping",
                #     "execution_device": "ubuntu1",
                #     "group_id": "advanced_services", 
                #     "parameters": {
                #         "target_ip": "192.168.102.2",
                #         "ping_count": 1
                #     },
                #     "test_cases": [
                #         {
                #             "comparison_type": "success",
                #             "expected_result": True
                #         }
                #     ]
                # },
                
                # # Test 8: SSH connectivity from Ubuntu1 to Ubuntu2
                # {
                #     "task_id": "ssh_inter_vlan",
                #     "template_name": "linux_remote_ssh",
                #     "execution_mode": "shared",
                #     "execution_device": "ubuntu1",
                #     "group_id": "advanced_services",
                #     "parameters": {
                #         "target_ip": "192.168.102.2",
                #         "ssh_user": "ubuntu",  # Adjust if different
                #         "ssh_password": "ubuntu",  # Adjust if different
                #     },
                #     "test_cases": [
                #         {
                #             "comparison_type": "success",
                #             "expected_result": True
                #         }
                #     ]
                # },
                
                # # Test 9: Internet connectivity from Ubuntu1 (Individual Task)
                # {
                #     "task_id": "ubuntu1_internet",
                #     "template_name": "network_ping",
                #     "execution_device": "ubuntu1",
                #     "parameters": {
                #         "target_ip": "8.8.8.8",
                #         "ping_count": 3
                #     },
                #     "test_cases": [
                #         {
                #             "comparison_type": "success", 
                #             "expected_result": True
                #         }
                #     ],
                #     "points": 10
                # },
                
                # Test 10: Custom debug example (Individual Task)
                {
                    "task_id": "debug_test",
                    "template_name": "debug_example",
                    "execution_device": "router",
                    "parameters": {
                        "target_ip": "192.168.102.2",
                        "ping_count": 3
                    },
                    # "test_cases": [
                    #     {
                    #         "comparison_type": "success",
                    #         "expected_result": True
                    #     }
                    # ],
                    "points": 7
                }
            ],
        # "groups": [
        #         {
        #             "group_id": "router_interfaces",
        #             "title": "Router Interface Configuration",
        #             "description": "All router VLAN interfaces must be properly configured and operational",
        #             "group_type": "proportional",
        #             "points": 16,
        #             "continue_on_failure": True,
        #             "timeout_seconds": 120
        #         },
        #         {
        #             "group_id": "basic_connectivity", 
        #             "title": "Basic Network Connectivity",
        #             "description": "Router must be able to reach all devices in both VLANs",
        #             "group_type": "all_or_nothing", 
        #             "points": 30,
        #             "continue_on_failure": True,
        #             "timeout_seconds": 180
        #         },
        #         {
        #             "group_id": "gateway_connectivity",
        #             "title": "Gateway Connectivity Test",
        #             "description": "Devices should be able to reach their default gateways - partial credit allowed",
        #             "group_type": "proportional",
        #             "points": 20,
        #             "continue_on_failure": True,
        #             "timeout_seconds": 90
        #         },
        #         {
        #             "group_id": "advanced_services",
        #             "title": "Advanced Network Services", 
        #             "description": "Inter-VLAN routing and SSH services - partial credit allowed",
        #             "group_type": "proportional",
        #             "points": 25,
        #             "continue_on_failure": True,
        #             "timeout_seconds": 200
        #         }
        #     ]
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
    "callback_url": "http://10.50.37.43:4000/v0/submissions"  # Set to your callback URL if needed
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
    # print("\n🔍 Testing enhanced device detection...")
    # try:
    #     detection_results = await grading_service.detect_devices(job)
    #     print(f"   📊 Detection Summary:")
        
    #     snmp_devices = [d for d in detection_results.values() if d.get('detection_method') == 'snmp']
    #     static_devices = [d for d in detection_results.values() if d.get('detection_method') == 'static']
        
    #     print(f"   └─ SNMP Detection: {len(snmp_devices)} devices")
    #     print(f"   └─ Static Detection: {len(static_devices)} devices")
    #     print()
        
    #     for device_id, result in detection_results.items():
    #         method_icon = "🌐" if result.get('detection_method') == 'snmp' else "📋"
    #         snmp_status = "✅" if result.get('snmp_enabled') else "❌"
    #         detection_time = result.get('detection_time', 0.0)
            
    #         print(f"   {method_icon} {device_id}:")
    #         print(f"      └─ Vendor: {result.get('vendor', 'Unknown')}")
    #         print(f"      └─ Model: {result.get('model', 'Unknown')}")
    #         print(f"      └─ Platform: {result.get('platform', 'unknown')}")
    #         print(f"      └─ OS Version: {result.get('os_version', 'Unknown')}")
    #         print(f"      └─ SNMP Enabled: {snmp_status}")
    #         print(f"      └─ Detection Time: {detection_time:.3f}s")
    #         print(f"      └─ Optimal Plugins: {', '.join(result.get('optimal_plugins', []))}")
            
    #         # Show raw SNMP data if available
    #         raw_data = result.get('raw_data', {})
    #         if raw_data:
    #             print(f"      └─ Raw SNMP Data:")
    #             for key, value in raw_data.items():
    #                 print(f"         • {key}: {value[:100]}{'...' if len(str(value)) > 100 else ''}")
    #         print()
            
    # except Exception as e:
    #     print(f"⚠️ Enhanced device detection failed: {e}")
    #     import traceback
    #     traceback.print_exc()
    
    # Test job validation
    print("\n📋 Validating job...")
    validation = await grading_service.validate_job_payload(job)
    if validation['valid']:
        print("✅ Job validation passed")
    else:
        print("❌ Job validation failed:")
        for error in validation['errors']:
            print(f"   - {error}")
        return
    
    # Run the actual grading
    print(f"\n🎯 Running grading test ({len(job.part.ansible_tasks)} tasks)...")
    try:
        result = await grading_service.process_grading_job(job)
        
        print(f"\n📊 GRADING RESULTS:")
        print(f"   Status: {result.status}")
        print(f"   Score: {result.total_points_earned}/{result.total_points_possible}")
        print(f"   Success Rate: {(result.total_points_earned/result.total_points_possible*100):.1f}%")
        print(f"   Execution Time: {result.total_execution_time:.2f}s")
        
        # Show group results if available
        if hasattr(result, 'group_results') and result.group_results:
            print(f"\n📊 TASK GROUP RESULTS:")
            for group in result.group_results:
                status_emoji = "✅" if group.status == "passed" else ("🟡" if group.status == "partial" else "❌")
                print(f"   {status_emoji} {group.title} ({group.group_type})")
                print(f"      └─ Status: {group.status}")
                print(f"      └─ Points: {group.points_earned}/{group.points_possible}")
                print(f"      └─ Tasks: {len(group.task_results)}")
                print(f"      └─ Message: {group.message}")
                if hasattr(group, 'rescue_executed') and group.rescue_executed:
                    print(f"      └─ 🚨 Rescue tasks executed")
                if hasattr(group, 'cleanup_executed') and group.cleanup_executed:
                    print(f"      └─ 🧹 Cleanup tasks executed")
                print()
        
        print(f"\n📝 Individual Test Results:")
        # Group tests by group_id for better organization
        grouped_tests = {}
        ungrouped_tests = []
        
        for test in result.test_results:
            if hasattr(test, 'group_id') and test.group_id:
                if test.group_id not in grouped_tests:
                    grouped_tests[test.group_id] = []
                grouped_tests[test.group_id].append(test)
            else:
                ungrouped_tests.append(test)
        
        # Show grouped tests
        for group_id, tests in grouped_tests.items():
            print(f"\n   📂 Group: {group_id}")
            for test in tests:
                status_emoji = "✅" if test.status == "passed" else ("⚠️" if test.status == "partial" else "❌")
                print(f"      {status_emoji} {test.test_name}: {test.status}")
                if test.message:
                    print(f"         └─ {test.message}")
        
        # Show ungrouped tests
        if ungrouped_tests:
            print(f"\n   📋 Individual Tasks:")
            for test in ungrouped_tests:
                status_emoji = "✅" if test.status == "passed" else ("⚠️" if test.status == "partial" else "❌")
                print(f"      {status_emoji} {test.test_name}: {test.status} ({test.points_earned}/{test.points_possible} pts)")
                if test.message:
                    print(f"         └─ {test.message}")
        
        # Show cancellation info if applicable  
        if hasattr(result, 'cancelled_reason') and result.cancelled_reason:
            print(f"\n⚠️  EXECUTION CANCELLED:")
            print(f"   Reason: {result.cancelled_reason}")
        
    except Exception as e:
        print(f"❌ Grading test failed: {e}")
        import traceback
        traceback.print_exc()

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