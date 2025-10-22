"""Playground script for exercising the snapshot collector."""

import asyncio

from app.services.grading.network_grader import Device as SimpleDevice
from app.services.grading.nornir_grading_service import NornirGradingService
from app.services.pipeline.snapshot_collector import SnapshotCollector


async def main():
    grading_service = NornirGradingService()

    # Define a minimal topology for testing; replace credentials with real ones.
    sample_devices = [
        SimpleDevice(
            id="ubuntu1",
            ip_address="172.40.210.130",
            username="ubuntu",
            password="ubuntu",
            device_type="linux",
        ),
        SimpleDevice(
            id="ubuntu2",
            ip_address="172.40.117.34",
            username="ubuntu",
            password="ubuntu",
            device_type="linux",
        ),
        SimpleDevice(
            id="router1",
            ip_address="10.70.38.101",
            username="admin",
            password="cisco",
            device_type="cisco_router",
        ),
    ]

    for device in sample_devices:
        await grading_service.add_device(device)

    collector = SnapshotCollector(grading_service=grading_service)

    result = await collector.collect_and_upload(
        course_name="Network101",
        lab_name="Lab1",
        student_id="student123",
    )

    print("Uploaded objects:", result)


if __name__ == "__main__":
    asyncio.run(main())