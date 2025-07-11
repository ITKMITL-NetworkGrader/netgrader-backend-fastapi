import os

class Config:
    # RabbitMQ Configuration
    RABBITMQ_URL: str = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
    GRADING_QUEUE: str = os.getenv("GRADING_QUEUE", "grading_jobs")
    
    # Ansible Configuration
    ANSIBLE_INVENTORY_DIR: str = os.getenv("ANSIBLE_INVENTORY_DIR", "/tmp/netgrader/inventories")
    ANSIBLE_PLAYBOOK_DIR: str = os.getenv("ANSIBLE_PLAYBOOK_DIR", "/tmp/netgrader/playbooks")
    TEMPLATES_DIR: str = os.getenv("TEMPLATES_DIR", "./templates")
    
    # API Configuration for callbacks
    CALLBACK_TIMEOUT: int = int(os.getenv("CALLBACK_TIMEOUT", "30"))
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

config = Config()
