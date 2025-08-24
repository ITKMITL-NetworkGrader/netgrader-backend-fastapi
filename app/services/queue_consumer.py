import asyncio
import json
import logging
from typing import Optional
import aio_pika
from aio_pika import connect_robust, Message, IncomingMessage
from app.schemas.models import GradingJob
# Legacy imports (no longer used)
# from app.services.grading_service import GradingService
# from app.services.nornir_grading.network_grading_service import NetworkGradingService

# Current grading service
from app.services.simple_grading_service import SimpleGradingService as GradingService
from app.core.config import config

logger = logging.getLogger(__name__)

class QueueConsumer:
    """
    Job Consumption: FastAPI worker constantly listening to RabbitMQ queue
    
    This class implements the core requirement of job consumption where the FastAPI worker
    continuously listens to the RabbitMQ queue and picks up grading jobs as they arrive.
    """
    
    def __init__(self):
        self.grading_service = GradingService()
        self.connection: Optional[aio_pika.abc.AbstractRobustConnection] = None
        self.channel: Optional[aio_pika.abc.AbstractChannel] = None
        self.queue: Optional[aio_pika.abc.AbstractQueue] = None
        self.is_running = False
        self.cleanup_task: Optional[asyncio.Task] = None
    
    async def connect(self):
        """Establish connection to RabbitMQ"""
        try:
            self.connection = await connect_robust(config.RABBITMQ_URL)
            self.channel = await self.connection.channel()
            
            # Set QoS to process one message at a time per worker
            await self.channel.set_qos(prefetch_count=1)
            
            # Declare the grading queue
            self.queue = await self.channel.declare_queue(
                config.GRADING_QUEUE,
                durable=True  # Survive broker restart
            )
            
            logger.info(f"Connected to RabbitMQ and declared queue: {config.GRADING_QUEUE}")
            
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            raise
    
    async def disconnect(self):
        """Close RabbitMQ connection"""
        self.is_running = False
        
        # Cancel periodic cleanup task
        if self.cleanup_task and not self.cleanup_task.done():
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
        
        if self.connection and not self.connection.is_closed:
            await self.connection.close()
            logger.info("Disconnected from RabbitMQ")
    
    async def start_consuming(self):
        """
        Start consuming messages from the grading queue
        Core Feature: Job Consumption - Worker constantly listening to queue
        """
        if not self.queue:
            await self.connect()
        
        self.is_running = True
        logger.info("🚀 FastAPI Worker: Starting to consume grading jobs from RabbitMQ queue")
        logger.info(f"📡 Listening on queue: {config.GRADING_QUEUE}")
        
        # Start consuming messages
        await self.queue.consume(self._process_message)
        
        # Start periodic cleanup task
        self.cleanup_task = asyncio.create_task(self._periodic_cleanup())
        logger.info("🧹 Started periodic cleanup task")
        
        # Keep the consumer running
        try:
            while self.is_running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Received interrupt signal, stopping consumer...")
        finally:
            await self.disconnect()
    
    async def _process_message(self, message: IncomingMessage):
        """
        Process incoming grading job message
        Core Feature: Job Consumption - Pick up and process jobs from queue
        """
        async with message.process():
            try:
                # Parse the job payload
                job_data = json.loads(message.body.decode())
                job = GradingJob(**job_data)
                
                logger.info(f"📥 Received grading job from queue: {job.job_id}")
                logger.info(f"👨‍🎓 Student: {job.student_id} | 📚 Lab: {job.lab_id}")
                logger.info(f"🧩 Part: {job.part.title} | 🎭 Play: {job.part.play.play_id}")
                total_tasks = len(job.part.play.ansible_tasks)
                logger.info(f"🧪 Total tasks to run: {total_tasks}")
                
                # Process the grading job (triggers dynamic playbook generation and execution)
                result = await self.grading_service.process_grading_job(job)
                logger.info(f"✅ Successfully processed job: {job.job_id}")
                
            except json.JSONDecodeError as e:
                logger.error(f"❌ Failed to parse job message: {e}")
                logger.error(f"Message body: {message.body.decode()}")
                # Don't requeue malformed messages
                
            except Exception as e:
                logger.error(f"❌ Error processing grading job: {e}")
                # The message will be requeued automatically due to exception
                raise
    
    async def publish_job(self, job: GradingJob):
        """Publish a grading job to the queue (useful for testing)"""
        if not self.channel:
            await self.connect()
        
        message = Message(
            job.model_dump_json().encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT  # Survive broker restart
        )
        
        await self.channel.default_exchange.publish(
            message,
            routing_key=config.GRADING_QUEUE
        )
        
        logger.info(f"Published job to queue: {job.job_id}")
    
    async def _periodic_cleanup(self):
        """Background task for periodic cleanup of old files"""
        while self.is_running:
            try:
                # Wait for cleanup interval (run every hour)
                await asyncio.sleep(3600)  # 1 hour
                
                if not self.is_running:
                    break
                    
                # Perform cleanup
                logger.info("🧹 Running periodic cleanup of old files")
                self.grading_service.cleanup_old_files()
                
            except asyncio.CancelledError:
                logger.info("🧹 Periodic cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in periodic cleanup: {e}")
                # Continue running even if cleanup fails
                continue

# Global consumer instance
consumer = QueueConsumer()

async def start_consumer():
    """Start the queue consumer"""
    await consumer.start_consuming()

async def stop_consumer():
    """Stop the queue consumer"""
    await consumer.disconnect()