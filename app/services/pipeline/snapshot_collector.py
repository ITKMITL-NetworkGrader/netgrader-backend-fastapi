import json
import logging
from typing import Dict, List, Optional

from minio.error import S3Error
from nornir_netmiko import netmiko_send_command
from nornir_napalm.plugins.tasks import napalm_get

from app.services.connectivity import MinioService
from app.services.grading.nornir_grading_service import NornirGradingService
from app.schemas.models import ExecutionMode

logger = logging.getLogger(__name__)


class SnapshotCollector:
    """Collects network snapshots and uploads them to object storage."""

    def __init__(
        self,
        grading_service: NornirGradingService,
        storage: Optional[MinioService] = None,
    ) -> None:
        self.grading_service = grading_service
        self.storage = storage or MinioService()

    async def collect_and_upload(
        self,
        course_name: str,
        lab_name: str,
        student_id: str,
        device_ids: Optional[List[str]] = None,
        bucket_name: Optional[str] = None,
    ) -> Dict[str, List[str]]:
        """Collect configs and host data, then upload them.

        Returns lists of uploaded object keys for configs and hosts.
        """
        await self._ensure_bucket(bucket_name)

        devices = self.grading_service.connection_manager.devices
        selected_ids = device_ids or list(devices.keys())

        config_objects: List[str] = []
        host_objects: List[str] = []

        for device_id in selected_ids:
            device = devices.get(device_id)
            if not device:
                logger.warning("Device %s not registered with nornir service", device_id)
                continue

            device_platform = (device.platform or "").lower()

            key_prefix = f"snapshots/{self._build_prefix(course_name, lab_name, student_id)}"

            if "linux" in device_platform:
                host_payload = await self._collect_host_data(device_id)
                if not host_payload:
                    continue
                object_key = f"{key_prefix}/hosts/{device.id}.json"
                await self._upload_json(object_key, host_payload, bucket_name)
                host_objects.append(object_key)
            else:
                config_payload = await self._collect_network_config(device_id)
                if not config_payload:
                    continue
                object_key = f"{key_prefix}/configs/{device.id}.cfg"
                await self._upload_text(object_key, config_payload, bucket_name)
                config_objects.append(object_key)

        return {
            "configs": config_objects,
            "hosts": host_objects,
        }

    async def _collect_network_config(self, device_id: str) -> Optional[str]:
        try:
            device = self.grading_service.connection_manager.devices.get(device_id)
            device_platform = (device.platform or "").lower() if device else ""
            if "telnet" in device_platform:
                logger.info(
                    "Skipping NAPALM config snapshot for %s (platform=%s): NAPALM is SSH-only",
                    device_id,
                    device_platform,
                )
                return None

            async with self.grading_service.connection_manager.get_connection(
                device_id=device_id,
                connection_mode=ExecutionMode.ISOLATED,
            ) as context:
                device_nr = self.grading_service.connection_manager.get_filtered_nornir(context, device_id)
                result = device_nr.run(
                    task=napalm_get,
                    getters=["config"],
                    name="snapshot_config",
                )
                device_result = result[device_id]
                if device_result.failed:
                    logger.error("Failed to collect config from %s: %s", device_id, device_result.exception)
                    return None
                config_data = device_result.result.get("config", {})
                running = config_data.get("running")
                if not running:
                    logger.error("No running configuration returned for %s", device_id)
                return running
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Unhandled error collecting config from %s: %s", device_id, exc)
            return None

    async def _collect_host_data(self, device_id: str) -> Optional[Dict[str, object]]:
        try:
            async with self.grading_service.connection_manager.get_connection(
                device_id=device_id,
                connection_mode=ExecutionMode.ISOLATED,
            ) as context:
                device_nr = self.grading_service.connection_manager.get_filtered_nornir(context, device_id)

                ip_result = device_nr.run(
                    task=netmiko_send_command,
                    command_string="ip -json addr show",
                    name="snapshot_ip_data",
                )
                route_result = device_nr.run(
                    task=netmiko_send_command,
                    command_string="ip route show default",
                    name="snapshot_routes",
                )

                ip_output = ip_result[device_id]
                route_output = route_result[device_id]

                if ip_output.failed:
                    logger.error("Failed to collect interface data from %s: %s", device_id, ip_output.exception)
                    return None

                interfaces_data = json.loads(ip_output.result)
                gateways = self._parse_gateways(route_output.result if not route_output.failed else "")
                host_interfaces = self._build_host_interfaces(interfaces_data, gateways)

                if not host_interfaces:
                    logger.warning("No host interfaces detected for %s", device_id)

                return {
                    "hostname": device_id,
                    "hostInterfaces": host_interfaces,
                }
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Unhandled error collecting host data from %s: %s", device_id, exc)
            return None

    async def _upload_text(self, object_key: str, payload: str, bucket_name: Optional[str]) -> None:
        data = payload.encode("utf-8")
        await self.storage.upload_data(object_key, data, length=len(data), bucket_name=bucket_name)

    async def _upload_json(self, object_key: str, payload: Dict[str, object], bucket_name: Optional[str]) -> None:
        content = json.dumps(payload, indent=2, sort_keys=True)
        await self._upload_text(object_key, content, bucket_name)

    async def _ensure_bucket(self, bucket_name: Optional[str]) -> None:
        try:
            await self.storage.ensure_bucket(bucket_name)
        except S3Error:
            logger.exception("Failed to ensure MinIO bucket exists")
            raise

    @staticmethod
    def _build_prefix(course_name: str, lab_name: str, student_id: str) -> str:
        safe_course = course_name.strip().replace(" ", "_")
        safe_lab = lab_name.strip().replace(" ", "_")
        safe_student = student_id.strip().replace(" ", "_")
        return f"{safe_course}/{safe_lab}/{safe_student}"

    @staticmethod
    def _parse_gateways(route_output: str) -> Dict[str, str]:
        gateways: Dict[str, str] = {}
        for line in route_output.splitlines():
            parts = line.split()
            if not parts or parts[0] != "default":
                continue
            try:
                via_index = parts.index("via")
                dev_index = parts.index("dev")
                gateways[parts[dev_index + 1]] = parts[via_index + 1]
            except (ValueError, IndexError):
                continue
        return gateways

    @staticmethod
    def _build_host_interfaces(interfaces_data: List[Dict[str, object]], gateways: Dict[str, str]) -> Dict[str, Dict[str, str]]:
        host_interfaces: Dict[str, Dict[str, str]] = {}
        for entry in interfaces_data:
            iface = entry.get("ifname")
            if not isinstance(iface, str):
                continue
            addr_info = entry.get("addr_info")
            if not isinstance(addr_info, list):
                continue

            prefix = None
            for item in addr_info:
                if item.get("family") == "inet":
                    local = item.get("local")
                    prefixlen = item.get("prefixlen")
                    if local and prefixlen is not None:
                        prefix = f"{local}/{prefixlen}"
                        break

            if not prefix:
                continue

            host_interfaces[iface] = {"name": iface, "prefix": prefix}
            gateway = gateways.get(iface)
            if gateway:
                host_interfaces[iface]["gateway"] = gateway

        return host_interfaces