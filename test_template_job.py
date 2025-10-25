#!/usr/bin/env python3
"""
Task Template Testing Job Payloads

Simple test jobs to validate custom task templates like:
- advanced_ping_test
- ospf_neighbor_check
- interface_status_check
- vlan_verification
- linux_service_health
- routing_validation
"""

import asyncio
from app.services.grading.simple_grading_service import SimpleGradingService
from app.schemas.models import GradingJob


# Test Job 1: Advanced Ping Test Template
ADVANCED_PING_TEST_JOB = {
    "job_id": "test_advanced_ping_001",
    "student_id": "student_test",
    "lab_id": "ping_test_lab",
    "part": {
        "part_id": "part1",
        "title": "Advanced Ping Test",
        "network_tasks": [
            {
                "task_id": "ping_server",
                "name": "Ping Server2",
                "template_name": "advanced_ping_test",  # Custom template
                "execution_device": "router1",
                "parameters": {
                    "target_ip": "172.40.117.34"  # IP address (union type test)
                },
                "test_cases": [],
                "points": 10
            },
            {
                "task_id": "ping_switch",
                "name": "Ping Switch",
                "template_name": "advanced_ping_test",
                "execution_device": "router1",
                "parameters": {
                    "target_ip": "172.40.210.190"  # Domain name (union type test)
                },
                "test_cases": [],
                "points": 10
            }
        ],
        "groups": []
    },
    "devices": [
        {
            "id": "router1",
            "ip_address": "10.70.38.101",
            "connection_type": "ssh",
            "credentials": {
                "username": "admin",
                "password": "cisco"
            },
            "platform": "cisco_ios",
            "role": "direct"
        }
    ],
    "ip_mappings": {}
}


# Test Job 2: VLAN Verification Template
VLAN_VERIFICATION_TEST_JOB = {
    "job_id": "test_vlan_verification_001",
    "student_id": "student_test",
    "lab_id": "vlan_test_lab",
    "part": {
        "part_id": "part1",
        "title": "VLAN Configuration Test",
        "network_tasks": [
            {
                "task_id": "verify_vlan_100",
                "name": "Verify VLAN 100 on Interface",
                "template_name": "vlan_verification",  # Custom template
                "execution_device": "router1",
                "parameters": {
                    "interface_name": "GigabitEthernet0/1",
                    "expected_vlan_id": 210
                },
                "test_cases": [],
                "points": 15
            },
            {
                "task_id": "verify_vlan_200",
                "name": "Verify VLAN 200 on Interface",
                "template_name": "vlan_verification",
                "execution_device": "router1",
                "parameters": {
                    "interface_name": "GigabitEthernet0/2",
                    "expected_vlan_id": 117
                },
                "test_cases": [],
                "points": 15
            }
        ],
        "groups": []
    },
    "devices": [
        {
            "id": "router1",
            "ip_address": "172.40.210.190",
            "connection_type": "ssh",
            "credentials": {
                "username": "admin",
                "password": "cisco"
            },
            "platform": "cisco_ios",
            "role": "direct"
        }
    ],
    "ip_mappings": {}
}


# Test Job 4: Interface Status Check Template
INTERFACE_STATUS_TEST_JOB = {
    "job_id": "test_interface_status_001",
    "student_id": "student_test",
    "lab_id": "interface_test_lab",
    "part": {
        "part_id": "part1",
        "title": "Interface Status Verification",
        "network_tasks": [
            {
                "task_id": "check_interface_status",
                "name": "Check interface status",
                "template_name": "interface_status_check",  # Custom template
                "execution_device": "router1",
                "parameters": {},
                "test_cases": [],
                "points": 15
            }
        ],
        "groups": []
    },
    "devices": [
        {
            "id": "router1",
            "ip_address": "10.70.38.101",
            "connection_type": "ssh",
            "credentials": {
                "username": "admin",
                "password": "cisco"
            },
            "platform": "cisco_ios",
            "role": "direct"
        }
    ],
    "ip_mappings": {}
}


# Test Job 5: Linux Service Health Check Template
LINUX_SERVICE_TEST_JOB = {
    "job_id": "test_linux_service_001",
    "student_id": "student_test",
    "lab_id": "service_test_lab",
    "part": {
        "part_id": "part1",
        "title": "Linux Service Health Check",
        "network_tasks": [
            {
                "task_id": "check_ssh_service",
                "name": "Verify SSH Service Running",
                "template_name": "linux_service_health",  # Custom template
                "execution_device": "server1",
                "parameters": {
                    "service_name": "ssh"
                },
                "test_cases": [],
                "points": 10
            },
            {
                "task_id": "check_network_service",
                "name": "Verify NetworkManager Service",
                "template_name": "linux_service_health",
                "execution_device": "server1",
                "parameters": {
                    "service_name": "NetworkManager"
                },
                "test_cases": [],
                "points": 10
            }
        ],
        "groups": []
    },
    "devices": [
        {
            "id": "server1",
            "ip_address": "172.40.117.34",
            "connection_type": "ssh",
            "credentials": {
                "username": "ubuntu",
                "password": "ubuntu"
            },
            "platform": "linux",
            "role": "direct"
        }
    ],
    "ip_mappings": {}
}


# Test Job 6: Multiple Templates Combined
COMBINED_TEMPLATES_TEST_JOB = {
    "job_id": "test_combined_templates_001",
    "student_id": "student_test",
    "lab_id": "combined_test_lab",
    "part": {
        "part_id": "part1",
        "title": "Combined Template Test",
        "network_tasks": [
            {
                "task_id": "ping_test",
                "name": "Network Connectivity",
                "template_name": "advanced_ping_test",
                "execution_device": "router1",
                "parameters": {
                    "target_ip": "172.40.210.190"
                },
                "test_cases": [],
                "points": 10
            },
            {
                "task_id": "service_test",
                "name": "Service Health",
                "template_name": "linux_service_health",
                "execution_device": "server1",
                "parameters": {
                    "service_name": "ssh"
                },
                "test_cases": [],
                "points": 10
            }
        ],
        "groups": []
    },
    "devices": [
        {
            "id": "server1",
            "ip_address": "172.40.210.130",
            "connection_type": "ssh",
            "credentials": {
                "username": "ubuntu",
                "password": "ubuntu"
            },
            "platform": "linux",
            "role": "direct"
        },
        {
            "id": "router1",
            "ip_address": "10.70.38.101",
            "connection_type": "ssh",
            "credentials": {
                "username": "admin",
                "password": "cisco"
            },
            "platform": "cisco_ios",
            "role": "direct"
        },
    ],
    "ip_mappings": {}
}

VLAN_TEST_JOB = {
    "job_id": "test_vlan_getter",
    "student_id": "student_test",
    "lab_id": "vlan_test_lab",
    "part": {
        "part_id": "part1",
        "title": "VLAN Data Verification",
        "network_tasks": [
            {
                "task_id": "check_vlan_data",
                "name": "Check VLAN data",
                "template_name": "vlan_napalm_get",
                "execution_device": "switch1",
                "parameters": {
                    "interface_name": "GigabitEthernet0/1",
                    "expected_vlan_id": 210
                },
                "test_cases": [],
                "points": 15
            }
        ],
        "groups": []
    },
    "devices": [
        {
            "id": "switch1",
            "ip_address": "172.40.210.190",
            "connection_type": "ssh",
            "credentials": {
                "username": "admin",
                "password": "cisco"
            },
            "platform": "cisco_ios",
            "role": "direct"
        }
    ],
    "ip_mappings": {}
}

ROUTE_TEST_JOB = {
    "job_id": "test_route_getter",
    "student_id": "student_test",
    "lab_id": "route_test_lab",
    "part": {
        "part_id": "part1",
        "title": "Route Data Verification",
        "network_tasks": [
            {
                "task_id": "check_route_data",
                "name": "Check Route data",
                "template_name": "routing_validation",
                "execution_device": "router1",
                "parameters": {
                    "target_network": "0.0.0.0/0",
                    "expected_next_hop": "10.70.38.1",
                },
                "test_cases": [],
                "points": 15
            }
        ],
        "groups": []
    },
    "devices": [
        {
            "id": "router1",
            "ip_address": "10.70.38.101",
            "connection_type": "ssh",
            "credentials": {
                "username": "admin",
                "password": "cisco"
            },
            "platform": "cisco_ios",
            "role": "direct"
        }
    ],
    "ip_mappings": {}
}

DHCP_TEST_JOB = {
    "job_id": "test_dhcp",
    "student_id": "student_test",
    "lab_id": "dhcp_test_lab",
    "part": {
        "part_id": "part1",
        "title": "DHCP Data Verification",
        "network_tasks": [
            {
                "task_id": "check_dhcp_binding",
                "name": "Check DHCP binding",
                "template_name": "dhcp_binding",
                "execution_device": "router1",
                "parameters": {
                    "expected_lease_ip": "172.40.117.34"
                },
                "test_cases": [],
                "points": 15
            }
        ],
        "groups": []
    },
    "devices": [
        {
            "id": "router1",
            "ip_address": "10.70.38.101",
            "connection_type": "ssh",
            "credentials": {
                "username": "admin",
                "password": "cisco"
            },
            "platform": "cisco_ios",
            "role": "direct"
        }
    ],
    "ip_mappings": {}
}


async def test_template(job_dict, test_name):
    """Run a single template test"""
    print(f"\n{'='*80}")
    print(f"🧪 TEST: {test_name}")
    print(f"{'='*80}")
    
    # Initialize grading service
    grading_service = SimpleGradingService()
    await grading_service.initialize()
    
    # Create job
    job = GradingJob(**job_dict)
    
    # Validate job
    print(f"📋 Validating job with {len(job.part.network_tasks)} tasks...")
    validation = await grading_service.validate_job_payload(job)
    
    if not validation['valid']:
        print("❌ Job validation failed:")
        for error in validation['errors']:
            print(f"   - {error}")
        return False
    
    print("✅ Job validation passed")
    
    # Show template info
    print(f"\n📦 Templates used:")
    for task in job.part.network_tasks:
        print(f"   • {task.template_name}")
        print(f"     └─ Task: {task.name or task.task_id}")
        print(f"     └─ Device: {task.execution_device}")
        print(f"     └─ Parameters: {task.parameters}")
    
    # Run grading (optional - uncomment to actually execute)
    print(f"\n⚠️  Grading execution disabled in test mode")
    print(f"   To run actual grading, uncomment the execution code below")
    
    # Uncomment to run actual grading:
    try:
        print(f"\n🎯 Running grading...")
        result = await grading_service.process_grading_job(job)
        
        print(f"\n📊 RESULTS:")
        print(f"   Status: {result.status}")
        print(f"   Score: {result.total_points_earned}/{result.total_points_possible}")
        print(f"   Execution Time: {result.total_execution_time:.2f}s")
        
        for test_result in result.test_results:
            status_emoji = "✅" if test_result.status == "passed" else "❌"
            print(f"   {status_emoji} {test_result.test_name}: {test_result.message}")
        
        return result.status == "completed"
    except Exception as e:
        print(f"❌ Grading failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


async def main():
    """Run all template tests"""
    print("🏗️ Task Template Test Jobs")
    print("=" * 80)
    
    tests = [
        # (ADVANCED_PING_TEST_JOB, "Advanced Ping Test"),
        # (VLAN_VERIFICATION_TEST_JOB, "VLAN Verification"),
        # (INTERFACE_STATUS_TEST_JOB, "Interface Status Check"),
        # (LINUX_SERVICE_TEST_JOB, "Linux Service Health"),
        # (COMBINED_TEMPLATES_TEST_JOB, "Combined Templates"),
        # (VLAN_TEST_JOB, "VLAN NAPALM Get Test"),
        # (ROUTE_TEST_JOB, "Routing Validation Test"),
        (DHCP_TEST_JOB , "DHCP Binding Test")

    ]
    
    passed = 0
    failed = 0
    
    for job_dict, test_name in tests:
        try:
            success = await test_template(job_dict, test_name)
            if success:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ Test '{test_name}' failed with error: {e}")
            failed += 1
    
    # Summary
    print(f"\n{'='*80}")
    print(f"📊 TEST SUMMARY")
    print(f"{'='*80}")
    print(f"Total Tests: {passed + failed}")
    print(f"Passed: {passed} ✅")
    print(f"Failed: {failed} ❌")
    print(f"\n💡 TIP: Edit the device credentials and IPs above to match your topology")
    print(f"💡 TIP: Uncomment the grading execution code to run actual tests")


if __name__ == "__main__":
    print("📝 Task Template Test Jobs")
    print("This file contains test job payloads for custom task templates.")
    print("Update device IPs and credentials to match your environment.\n")
    
    asyncio.run(main())
