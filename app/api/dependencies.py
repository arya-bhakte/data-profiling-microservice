import os
from typing import Generator
from dotenv import load_dotenv
from app.worker.job_store import JobStore
from app.worker.rabbitmq_connection import RabbitMQPublisher, get_rabbitmq_params

# Load environment variables
load_dotenv()

# Configuration from environment
JOB_DB_PARAMS = {
    "host": os.getenv("JOB_DB_HOST", "localhost"),
    "database": os.getenv("JOB_DB_NAME", "profiling_jobs"),
    "user": os.getenv("JOB_DB_USER", "postgres"),
    "password": os.getenv("JOB_DB_PASSWORD", "postgres123"),
    "port": int(os.getenv("JOB_DB_PORT", "5432"))
}

RABBITMQ_QUEUE_NAME = os.getenv("RABBITMQ_QUEUE_NAME", "profiling_jobs")


def get_job_store() -> Generator[JobStore, None, None]:
    job_store = JobStore(JOB_DB_PARAMS)
    try:
        yield job_store
    finally:
        # Cleanup if needed
        pass


def get_rabbitmq_publisher() -> RabbitMQPublisher:
    rabbitmq_params = get_rabbitmq_params()
    return RabbitMQPublisher(
        rabbitmq_params=rabbitmq_params,
        queue_name=RABBITMQ_QUEUE_NAME
    )


def get_config() -> dict:
    return {
        "job_db_params": JOB_DB_PARAMS,
        "rabbitmq_queue_name": RABBITMQ_QUEUE_NAME
    }