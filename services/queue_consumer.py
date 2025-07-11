import asyncio
import json
import logging
from typing import Optional
import aio_pika
from aio_pika import connect_robust, Message, IncomingMessage
from models import GradingJob
from services.grading_service import GradingService
from config import config

logger = logging.getLogger(__name__)

class QueueConsumer:
    """RabbitMQ consumer for processing grading jobs"""
    
    def __init__(self):
        self.grading_service = GradingService()
        self.connection: Optional[aio_pika.abc.AbstractRobustConnection] = None
        self.channel: Optional[aio_pika.abc.AbstractChannel] = None
        self.queue: Optional[aio_pika.abc.AbstractQueue] = None
        self.is_running = False
    
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
        if self.connection and not self.connection.is_closed:
            await self.connection.close()
            logger.info("Disconnected from RabbitMQ")
    
    async def start_consuming(self):
        """Start consuming messages from the grading queue"""
        if not self.queue:
            await self.connect()
        
        self.is_running = True
        logger.info("Starting to consume grading jobs...")
        
        # Start consuming messages
        await self.queue.consume(self._process_message)
        
        # Keep the consumer running
        try:
            while self.is_running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Received interrupt signal, stopping consumer...")
        finally:
            await self.disconnect()
    
    async def _process_message(self, message: IncomingMessage):
        """Process incoming grading job message"""
        async with message.process():
            try:
                # Parse the job payload
                job_data = json.loads(message.body.decode())
                job = GradingJob(**job_data)
                
                logger.info(f"Received grading job: {job.job_id}")
                
                # Process the grading job
                result = await self.grading_service.process_grading_job(job)
                logger.info(f"Successfully processed job: {job.job_id}")
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse job message: {e}")
                logger.error(f"Message body: {message.body.decode()}")
                # Don't requeue malformed messages
                
            except Exception as e:
                logger.error(f"Error processing grading job: {e}")
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

# Global consumer instance
consumer = QueueConsumer()

async def start_consumer():
    """Start the queue consumer"""
    await consumer.start_consuming()

async def stop_consumer():
    """Stop the queue consumer"""
    await consumer.disconnect()