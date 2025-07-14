#!/usr/bin/env python3
"""
Pre-startup verification script for NetGrader
Checks if RabbitMQ is running and Ansible collections are installed
"""
import asyncio
import subprocess
import sys
import aio_pika
from app.core.config import config

async def check_rabbitmq():
    """Check if RabbitMQ is accessible"""
    print("🐰 Checking RabbitMQ connection...")
    try:
        connection = await aio_pika.connect_robust(config.RABBITMQ_URL)
        await connection.close()
        print("✅ RabbitMQ is running and accessible")
        return True
    except Exception as e:
        print(f"❌ RabbitMQ connection failed: {e}")
        print("   💡 Start RabbitMQ with: docker-compose up -d rabbitmq")
        return False

def check_ansible_collections():
    """Check if required Ansible collections are installed"""
    print("📦 Checking Ansible collections...")
    
    required_collections = [
        "ansible.netcommon",
        "cisco.ios",  # Required for Cisco IOS commands
        # "ansible.posix",      # Optional but recommended
        # "community.general"   # Optional but recommended
    ]
    
    missing_collections = []
    
    for collection in required_collections:
        try:
            result = subprocess.run(
                ["ansible-galaxy", "collection", "list", collection],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode == 0 and collection in result.stdout:
                print(f"✅ {collection} is installed")
            else:
                missing_collections.append(collection)
                print(f"❌ {collection} is NOT installed")
        except Exception as e:
            missing_collections.append(collection)
            print(f"❌ Error checking {collection}: {e}")
    
    if missing_collections:
        print("\n💡 Install missing collections with:")
        for collection in missing_collections:
            print(f"   ansible-galaxy collection install {collection}")
        return False
    else:
        print("✅ All required Ansible collections are installed")
        return True

async def main():
    """Main verification function"""
    print("🔍 NetGrader Pre-Startup Verification")
    print("=" * 40)
    
    rabbitmq_ok = await check_rabbitmq()
    print()
    
    ansible_ok = check_ansible_collections()
    print()
    
    if rabbitmq_ok and ansible_ok:
        print("🎉 All prerequisites are met!")
        print("✅ You can now start the NetGrader worker:")
        print("   python main.py")
    else:
        print("❌ Some prerequisites are missing.")
        print("   Please fix the issues above before starting the worker.")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
