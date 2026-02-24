"""Playground script for exercising the snapshot collector."""

import asyncio

from app.schemas.models import Device
from app.services.grading.nornir_grading_service import NornirGradingService
from app.services.pipeline.snapshot_collector import SnapshotCollector
from app.services.connectivity.api_client import APIClient
import json

async def main():
    grading_service = NornirGradingService()
    batfish_api = APIClient().batfish()
    payload = {
        "course_name": "Network101",
        "lab_name": "Lab1",
        "student_id": "student123",
    }
    # Define a minimal topology for testing; replace credentials with real ones.
    sample_devices = [
        Device(
            id="ubuntu1",
            ip_address="172.40.210.130",
            credentials={"username": "ubuntu", "password": "ubuntu"},
            platform="linux",
        ),
        Device(
            id="ubuntu2",
            ip_address="172.40.117.34",
            credentials={"username": "ubuntu", "password": "ubuntu"},
            platform="linux",
        ),
        Device(
            id="router1",
            ip_address="10.70.38.101",
            credentials={"username": "admin", "password": "cisco"},
            platform="cisco_router",
        ),
    ]

    for device in sample_devices:
        await grading_service.add_device(device)

    collector = SnapshotCollector(grading_service=grading_service)

    result = await collector.collect_and_upload(
        course_name=payload["course_name"],
        lab_name=payload["lab_name"],
        student_id=payload["student_id"],
    )

    print("Uploaded objects:", result)
    response = await batfish_api.post_acl_lines_minio(
        {
            "payload": {
                "nodes": None,  
                "properties": None,
                "filters": "100"
            },
            "minio_payload": {
                "batfish_ip": "10.0.24.2",
                "course_id": payload["course_name"],
                "lab_id": payload["lab_name"],
                "student_id": payload["student_id"]
            }
        }
    )
    print(json.dumps(response, indent=4))

if __name__ == "__main__":
    asyncio.run(main())