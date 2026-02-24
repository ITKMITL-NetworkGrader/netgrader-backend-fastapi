"""
Connection Manager for Nornir Task Execution

Provides connection isolation per task while supporting stateful execution
for tasks that need to share connection state.
"""

import logging
import tempfile
import os
import time
import yaml
from typing import Dict, Any, Optional, List, Union
from enum import Enum
from dataclasses import dataclass
from contextlib import asynccontextmanager

# Nornir imports
from nornir import InitNornir
from nornir.core.inventory import Inventory
from nornir.core.task import Task, Result

from app.schemas.models import Device, ExecutionMode

logger = logging.getLogger(__name__)



@dataclass
class ConnectionContext:
    """Context information for a connection session"""
    device_id: str
    connection_mode: ExecutionMode
    session_id: str
    start_time: float
    nr_instance: Optional[InitNornir] = None
    temp_dir: Optional[str] = None
    connection_state: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.connection_state is None:
            self.connection_state = {}

class ConnectionManager:
    """
    Manages Nornir connections with support for isolated and stateful execution modes.
    
    - ISOLATED: Each task gets a fresh Nornir instance and connection
    - STATEFUL: Tasks in a sequence share the same connection (for multi-step operations)  
    - SHARED: Multiple tasks share a connection pool (for performance optimization)
    """
    
    def __init__(self):
        self.devices: Dict[str, Device] = {}
        self.device_groups: Dict[str, List[str]] = {}
        self._active_connections: Dict[str, ConnectionContext] = {}
        self._connection_counter = 0
        self._shared_nr_instance: Optional[InitNornir] = None
        self._shared_temp_dir: Optional[str] = None
        
    async def add_device(self, device: Device):
        """Add a device to the connection manager"""
        self.devices[device.id] = device
        device_type = device.platform or "generic"
        logger.info(f"Added device to connection manager: {device.id} ({device.ip_address}) - {device_type}")
        
        # Categorize device into groups based on device_type
        if "cisco" in device_type.lower():
            if "router" in device_type.lower():
                group = "cisco_routers"
            elif "switch" in device_type.lower():
                group = "cisco_switches"
            else:
                group = "cisco_devices"
        elif "linux" in device_type.lower():
            group = "linux_servers"
        else:
            group = "generic_devices"
            
        if group not in self.device_groups:
            self.device_groups[group] = []
        self.device_groups[group].append(device.id)
    
    def _create_nornir_inventory(self, devices_subset: Optional[List[str]] = None) -> str:
        """Create dynamic Nornir inventory from devices or subset"""
        temp_dir = tempfile.mkdtemp(prefix="nornir_connection_")
        inventory_dir = os.path.join(temp_dir, 'inventory')
        os.makedirs(inventory_dir, exist_ok=True)
        
        # Use subset of devices if provided, otherwise all devices
        target_devices = devices_subset or list(self.devices.keys())
        
        # Create hosts.yaml
        hosts_data = {}
        for device_id in target_devices:
            if device_id not in self.devices:
                logger.warning(f"Device {device_id} not found in devices list")
                continue
                
            device = self.devices[device_id]
            # Determine platform for connection options
            device_type = device.platform or "generic"
            if "cisco" in device_type.lower():
                platform = "ios"
            elif "linux" in device_type.lower():
                platform = "linux"
            else:
                platform = "generic"
            
            # Determine netmiko device type
            netmiko_device_type = device_type
            if netmiko_device_type in ["cisco", "cisco_router", "cisco_switch"]:
                netmiko_device_type = "cisco_ios"
            elif netmiko_device_type == "linux_server":
                netmiko_device_type = "linux"
            elif netmiko_device_type == "linux_telnet":
                netmiko_device_type = "generic_telnet"

            is_telnet_device = "telnet" in device_type.lower() or "telnet" in netmiko_device_type.lower()
            host_config = {
                'hostname': device.ip_address,
                'port': device.port,
                'username': device.credentials.get("username", ""),
                'password': device.credentials.get("password", ""),
                'platform': platform,
                'groups': [],
                'data': {
                    'is_localhost': device.ip_address in ["localhost", "127.0.0.1"] or device.ip_address.startswith("127."),
                    'device_os': device.device_os  # Add device_os for parsing
                },
                'connection_options': {
                    'netmiko': {
                        'extras': {
                            'device_type': netmiko_device_type
                        }
                    }
                }
            }

            # NAPALM is SSH-only; do not configure it for telnet platforms.
            if not is_telnet_device:
                host_config['connection_options']['napalm'] = {
                    'extras': {
                        'optional_args': {
                            'transport': 'ssh'
                        }
                    }
                }

            # Add to appropriate groups
            for group, device_ids in self.device_groups.items():
                if device.id in device_ids:
                    host_config['groups'].append(group)
                    
            hosts_data[device.id] = host_config
            
        hosts_file = os.path.join(inventory_dir, 'hosts.yaml')
        with open(hosts_file, 'w') as f:
            yaml.dump(hosts_data, f, default_flow_style=False)
            
        # Create groups.yaml with connection configurations
        groups_data = {}
        
        # Cisco groups with optimized connection settings
        for group_name in ['cisco_routers', 'cisco_switches', 'cisco_devices']:
            if group_name in self.device_groups:
                groups_data[group_name] = {
                    'platform': 'ios',
                    'connection_options': {
                        'netmiko': {
                            'platform': 'cisco_ios',
                            'extras': {
                                'device_type': 'cisco_ios',
                                'global_delay_factor': 2,
                                'timeout': 30,
                                'session_timeout': 60,
                                'auth_timeout': 30,
                                'banner_timeout': 15,
                                'blocking_timeout': 20,
                                'conn_timeout': 10
                            }
                        }
                    }
                }
        
        # Linux servers group with SSH optimizations
        if 'linux_servers' in self.device_groups:
            groups_data['linux_servers'] = {
                'platform': 'linux',
                'connection_options': {
                    'netmiko': {
                        'platform': 'linux',
                        'extras': {
                            'device_type': 'linux',
                            'timeout': 30,
                            'session_timeout': 60,
                            'auth_timeout': 30,
                            'banner_timeout': 15,
                            'conn_timeout': 10
                        }
                    }
                }
            }
            
        # Generic devices group
        if 'generic_devices' in self.device_groups:
            groups_data['generic_devices'] = {
                'platform': 'linux',  # Default to linux
                'connection_options': {
                    'netmiko': {
                        'platform': 'linux',
                        'extras': {
                            'device_type': 'linux',
                            'timeout': 30,
                            'session_timeout': 60
                        }
                    }
                }
            }
            
        groups_file = os.path.join(inventory_dir, 'groups.yaml')
        with open(groups_file, 'w') as f:
            yaml.dump(groups_data, f, default_flow_style=False)
            
        # Create config.yaml with optimized settings
        config_data = {
            'inventory': {
                'plugin': 'SimpleInventory',
                'options': {
                    'host_file': os.path.join(inventory_dir, 'hosts.yaml'),
                    'group_file': os.path.join(inventory_dir, 'groups.yaml')
                }
            },
            'runner': {
                'plugin': 'threaded',
                'options': {
                    'num_workers': min(len(target_devices), 5)  # Limit workers for connection isolation
                }
            },
            'logging': {
                'enabled': True,
                'level': 'WARNING'  # Reduce noise in logs
            }
        }
        
        config_file = os.path.join(temp_dir, 'config.yaml')
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f, default_flow_style=False)
            
        logger.debug(f"Created Nornir inventory in {inventory_dir} for devices: {target_devices}")
        return config_file, temp_dir
    
    @asynccontextmanager
    async def get_connection(self, device_id: str, connection_mode: ExecutionMode = ExecutionMode.ISOLATED, session_id: Optional[str] = None):
        """
        Get a connection context for executing tasks.
        
        Args:
            device_id: Target device ID
            connection_mode: Connection isolation mode
            session_id: Optional session ID for stateful connections
            
        Yields:
            ConnectionContext with Nornir instance
        """
        
        # Generate session ID if not provided
        if session_id is None:
            self._connection_counter += 1
            session_id = f"{device_id}_{connection_mode.value}_{self._connection_counter}_{int(time.time())}"
        
        context_key = f"{session_id}_{device_id}"
        start_time = time.time()
        
        try:
            # Check for existing connection in stateful/shared modes
            if connection_mode in [ExecutionMode.STATEFUL, ExecutionMode.SHARED]:
                if context_key in self._active_connections:
                    context = self._active_connections[context_key]
                    logger.debug(f"Reusing {connection_mode.value} connection for {device_id} (session: {session_id})")
                    yield context
                    return
            
            # Create new connection
            logger.debug(f"Creating {connection_mode.value} connection for {device_id} (session: {session_id})")
            
            if connection_mode == ExecutionMode.SHARED and self._shared_nr_instance:
                # Use shared instance
                nr_instance = self._shared_nr_instance
                temp_dir = self._shared_temp_dir
                logger.debug(f"Using shared Nornir instance for {device_id}")
            else:
                # Determine which devices to include in inventory
                if connection_mode == ExecutionMode.SHARED:
                    # For SHARED mode, create inventory with ALL devices
                    devices_for_inventory = list(self.devices.keys())
                    logger.debug(f"Creating shared inventory with all devices: {devices_for_inventory}")
                else:
                    # For ISOLATED/STATEFUL mode, use only current device
                    devices_for_inventory = [device_id]
                
                config_file, temp_dir = self._create_nornir_inventory(devices_for_inventory)
                nr_instance = InitNornir(config_file=config_file)
                
                # For shared mode, store the instance for reuse
                if connection_mode == ExecutionMode.SHARED:
                    self._shared_nr_instance = nr_instance
                    self._shared_temp_dir = temp_dir
            
            # Create connection context
            context = ConnectionContext(
                device_id=device_id,
                connection_mode=connection_mode,
                session_id=session_id,
                start_time=start_time,
                nr_instance=nr_instance,
                temp_dir=temp_dir
            )
            
            # Store context for stateful/shared modes
            if connection_mode in [ExecutionMode.STATEFUL, ExecutionMode.SHARED]:
                self._active_connections[context_key] = context
            
            logger.debug(f"Connection established for {device_id} ({connection_mode.value}) in {time.time() - start_time:.2f}s")
            yield context
            
        except Exception as e:
            logger.error(f"Failed to establish connection for {device_id}: {e}")
            raise
        finally:
            # Cleanup for isolated connections
            if connection_mode == ExecutionMode.ISOLATED:
                await self._cleanup_connection(context_key, context if 'context' in locals() else None)
    
    async def close_stateful_connection(self, device_id: str, session_id: str):
        """Explicitly close a stateful connection"""
        context_key = f"{session_id}_{device_id}"
        if context_key in self._active_connections:
            context = self._active_connections[context_key]
            await self._cleanup_connection(context_key, context)
            logger.debug(f"Closed stateful connection for {device_id} (session: {session_id})")
    
    async def _cleanup_connection(self, context_key: str, context: Optional[ConnectionContext]):
        """Clean up connection resources"""
        try:
            if context_key in self._active_connections:
                del self._active_connections[context_key]
            
            if context and context.temp_dir and context.connection_mode != ExecutionMode.SHARED:
                # Don't cleanup shared temp directory
                if os.path.exists(context.temp_dir):
                    import shutil
                    shutil.rmtree(context.temp_dir)
                    logger.debug(f"Cleaned up temp directory: {context.temp_dir}")
                    
        except Exception as e:
            logger.warning(f"Error during connection cleanup: {e}")
    
    def get_filtered_nornir(self, context: ConnectionContext, device_id: str):
        """Get a filtered Nornir instance for specific device"""
        if not context.nr_instance:
            raise RuntimeError("No Nornir instance in connection context")
        
        device_nr = context.nr_instance.filter(name=device_id)
        
        if not device_nr.inventory.hosts:
            raise RuntimeError(f"Device {device_id} not found in Nornir inventory")
        
        return device_nr
    
    async def cleanup_all(self):
        """Clean up all connections and resources"""
        logger.info("Cleaning up all connections...")
        
        # Close all active connections
        for context_key in list(self._active_connections.keys()):
            context = self._active_connections.get(context_key)
            await self._cleanup_connection(context_key, context)
        
        # Clean up shared resources
        if self._shared_temp_dir and os.path.exists(self._shared_temp_dir):
            import shutil
            shutil.rmtree(self._shared_temp_dir)
            self._shared_temp_dir = None
            self._shared_nr_instance = None
            
        logger.info("All connections cleaned up")
    
    async def clear_job_state(self):
        """Clear all devices and connections accumulated during a job.
        
        Call this after each job completes to prevent memory leaks.
        """
        logger.info(f"Clearing job state: {len(self.devices)} devices, "
                    f"{len(self._active_connections)} connections")
        
        # Close all active connections first
        await self.cleanup_all()
        
        # Clear device registrations
        self.devices.clear()
        self.device_groups.clear()
        
        logger.info("Job state cleared")
    
    def get_connection_stats(self) -> Dict[str, Any]:
        """Get statistics about active connections"""
        active_by_mode = {}
        for context in self._active_connections.values():
            mode = context.connection_mode.value
            active_by_mode[mode] = active_by_mode.get(mode, 0) + 1
        
        return {
            'total_active_connections': len(self._active_connections),
            'active_by_mode': active_by_mode,
            'has_shared_instance': self._shared_nr_instance is not None,
            'total_devices': len(self.devices)
        }