import os

class Config:
    # RabbitMQ Configuration
    RABBITMQ_URL: str = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
    GRADING_QUEUE: str = os.getenv("GRADING_QUEUE", "grading_jobs")
    
    # Ansible Configuration
    ANSIBLE_INVENTORY_DIR: str = os.getenv("ANSIBLE_INVENTORY_DIR", "/tmp/netgrader/inventories")
    ANSIBLE_PLAYBOOK_DIR: str = os.getenv("ANSIBLE_PLAYBOOK_DIR", "/tmp/netgrader/playbooks")
    TEMPLATES_DIR: str = os.getenv("TEMPLATES_DIR", "./templates")
    SHARED_TASKS_DIR: str = os.getenv("SHARED_TASKS_DIR", "/tmp/netgrader/shared_tasks")
    
    # API Configuration for callbacks
    CALLBACK_TIMEOUT: int = int(os.getenv("CALLBACK_TIMEOUT", "30"))
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    
    # Cleanup Configuration
    CLEANUP_FILES_AFTER_JOB: bool = os.getenv("CLEANUP_FILES_AFTER_JOB", "true").lower() == "true"
    CLEANUP_FILES_OLDER_THAN_HOURS: int = int(os.getenv("CLEANUP_FILES_OLDER_THAN_HOURS", "24"))
    PRESERVE_SHARED_TASKS_ON_RESTART: bool = os.getenv("PRESERVE_SHARED_TASKS_ON_RESTART", "true").lower() == "true"
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # SNMP Configuration for device detection
    SNMP_COMMUNITY: str = os.getenv("SNMP_COMMUNITY", "netgrader")
    SNMP_TIMEOUT: int = int(os.getenv("SNMP_TIMEOUT", "3"))
    SNMP_RETRIES: int = int(os.getenv("SNMP_RETRIES", "1"))
    SNMP_ENABLED: bool = os.getenv("SNMP_ENABLED", "true").lower() == "true"

config = Config()
