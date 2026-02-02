"""
RabbitMQ connection management - shared by API and Worker.

Responsibilities:
- Connection lifecycle (connect, disconnect)
- Queue declaration
- Publishing messages (for API)
- Setting up consumer (for Worker)

Does NOT handle:
- Job processing logic (worker.py)
- Job state management (job_store.py)
- ACK/NACK decisions (worker.py decides)
"""

import pika
import json
import logging
from typing import Dict, Optional, Callable

logger = logging.getLogger(__name__)


class RabbitMQConnection:
    """
    Manages RabbitMQ connection and basic operations.
    
    Design principle: This class is a thin wrapper around pika.
    It doesn't make decisions about job processing or error handling.
    """
    
    def __init__(
        self,
        host: str = 'localhost',
        port: int = 5672,
        username: str = 'guest',
        password: str = 'guest',
        queue_name: str = 'profiling_jobs'
    ):
        """
        Initialize RabbitMQ connection parameters.
        
        Connection is lazy - call connect() explicitly.
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.queue_name = queue_name
        
        self.connection: Optional[pika.BlockingConnection] = None
        self.channel: Optional[pika.channel.Channel] = None
    
    def connect(self):
        """
        Establish connection to RabbitMQ and declare queue.
        
        Raises:
            pika.exceptions.AMQPConnectionError: If connection fails
        """
        credentials = pika.PlainCredentials(
            username=self.username,
            password=self.password
        )
        
        parameters = pika.ConnectionParameters(
            host=self.host,
            port=self.port,
            credentials=credentials,
            heartbeat=600,
            blocked_connection_timeout=300
        )
        
        try:
            self.connection = pika.BlockingConnection(parameters)
            self.channel = self.connection.channel()
            
            # Declare queue (idempotent)
            self.channel.queue_declare(queue=self.queue_name, durable=True)
            
            logger.info(f"Connected to RabbitMQ at {self.host}:{self.port}")
            logger.info(f"Queue '{self.queue_name}' ready")
            
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            raise
    
    def publish_job(self, job_id: str):
        """
        Publish a job notification to the queue.
        
        Args:
            job_id: ID of the job to process
        
        Message format: {"job_id": "abc-123"}
        
        Called by: API after creating job in database
        
        Raises:
            RuntimeError: If not connected
        """
        if not self.channel:
            raise RuntimeError("Not connected to RabbitMQ. Call connect() first.")
        
        message = {"job_id": job_id}
        message_body = json.dumps(message)
        
        self.channel.basic_publish(
            exchange='',
            routing_key=self.queue_name,
            body=message_body,
            properties=pika.BasicProperties(
                delivery_mode=2,  # Persistent
                content_type='application/json'
            )
        )
        
        logger.info(f"Published job {job_id} to queue '{self.queue_name}'")
    
    def setup_consumer(self, callback: Callable, prefetch_count: int = 1):
        """
        Setup consumer with callback - does NOT start consuming.
        
        Args:
            callback: Function with signature:
                      callback(ch, method, properties, body) -> None
            prefetch_count: Number of unacked messages to prefetch
        
        Why this design:
        - Worker decides how to handle messages (ACK/NACK logic)
        - Worker gets full pika message context
        - More flexible than auto-ACK wrapper
        
        Usage:
            conn.setup_consumer(my_callback)
            conn.start_consuming()  # Blocks
        
        Raises:
            RuntimeError: If not connected
        """
        if not self.channel:
            raise RuntimeError("Not connected to RabbitMQ. Call connect() first.")
        
        # Set QoS
        self.channel.basic_qos(prefetch_count=prefetch_count)
        
        # Register consumer
        self.channel.basic_consume(
            queue=self.queue_name,
            on_message_callback=callback,
            auto_ack=False  # Manual ACK (worker controls)
        )
        
        logger.info(f"Consumer setup on queue '{self.queue_name}' (prefetch={prefetch_count})")
    
    def start_consuming(self):
        """
        Start consuming messages (blocking).
        
        This blocks forever until:
        - stop_consuming() is called
        - Exception is raised
        - Connection is closed
        
        Raises:
            RuntimeError: If not connected or consumer not setup
        """
        if not self.channel:
            raise RuntimeError("Not connected to RabbitMQ. Call connect() first.")
        
        logger.info("Starting to consume messages...")
        self.channel.start_consuming()
    
    def stop_consuming(self):
        """
        Stop consuming messages.
        
        Current message will finish processing before stopping.
        """
        if self.channel and self.channel.is_open:
            self.channel.stop_consuming()
            logger.info("Stopped consuming messages")
    
    def close(self):
        """
        Close connection to RabbitMQ.
        
        Always safe to call (checks if open first).
        """
        if self.channel and self.channel.is_open:
            try:
                self.channel.close()
            except Exception as e:
                logger.error(f"Error closing channel: {e}")
        
        if self.connection and self.connection.is_open:
            try:
                self.connection.close()
                logger.info("Disconnected from RabbitMQ")
            except Exception as e:
                logger.error(f"Error closing connection: {e}")


class RabbitMQPublisher:
    """
    Lightweight publisher for API use.
    
    For API endpoints that just need to publish messages
    without maintaining a persistent connection.
    
    Usage:
        publisher = RabbitMQPublisher(params)
        publisher.publish_job(job_id)  # Opens, publishes, closes
    """
    
    def __init__(self, rabbitmq_params: Dict[str, str], queue_name: str = "profiling_jobs"):
        self.rabbitmq_params = rabbitmq_params
        self.queue_name = queue_name
    
    def publish_job(self, job_id: str):
        """
        Publish a job message (one-shot connection).
        
        Opens connection, publishes message, closes connection.
        Simple and safe for API endpoints.
        """
        conn = RabbitMQConnection(
            host=self.rabbitmq_params.get('host', 'localhost'),
            port=self.rabbitmq_params.get('port', 5672),
            username=self.rabbitmq_params.get('username', 'guest'),
            password=self.rabbitmq_params.get('password', 'guest'),
            queue_name=self.queue_name
        )
        
        try:
            conn.connect()
            conn.publish_job(job_id)
        finally:
            conn.close()


def get_rabbitmq_params() -> Dict[str, str]:
    """
    Get RabbitMQ connection parameters.
    
    TODO: Read from environment variables in production
    """
    return {
        "host": "localhost",
        "port": 5672,
        "username": "guest",
        "password": "guest"
    }