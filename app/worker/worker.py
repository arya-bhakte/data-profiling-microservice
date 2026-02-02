import os
import logging
from dotenv import load_dotenv
import psycopg2
import json
from typing import Dict, List, Any

from app.worker.job_store import JobStore
from app.worker.models import Job, JobStatus
from app.worker.rabbitmq_connection import RabbitMQConnection
from app.core.table_profiler import profile_table
from app.core.ai_enrichment import enrich_profile_with_ai


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ProfileWorker:
   
    def __init__(
        self, 
        job_store: JobStore, 
        target_db_params: Dict[str, str],
        rabbitmq_conn: RabbitMQConnection
    ):

        self.job_store = job_store
        self.target_db_params = target_db_params
        self.rabbitmq_conn = rabbitmq_conn
        self.running = False
    
    def _get_target_connection(self):
        return psycopg2.connect(**self.target_db_params)
    
    def _message_callback(self, ch, method, properties, body):
        job_id = None
        try:
            # Parse message
            message_data = json.loads(body.decode('utf-8'))
            job_id = message_data.get('job_id')
            
            if not job_id:
                logger.error(f"Invalid message format (missing job_id): {body}")
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
                return
            
            logger.info(f"Received message for job {job_id}")
            
            # Fetch job from database
            job = self.job_store.get_job(job_id)
            
            if not job:
                logger.error(f"Job {job_id} not found in database")
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
                return
            
            # Validate job state
            if job.status != JobStatus.QUEUED:
                logger.warning(
                    f"Job {job_id} not in QUEUED state (current: {job.status}). "
                    f"Skipping processing."
                )
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return
            
            # Process the job 
            self.process_job(job)
            
            # Acknowledge message upon successful processing
            ch.basic_ack(delivery_tag=method.delivery_tag)
            logger.info(f"Acknowledged message for job {job_id}")
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse message as JSON: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            
        except Exception as e:
            logger.error(f"Unexpected error in message callback: {e}", exc_info=True)
            
            # NACK 
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            
            # Try to mark job as failed in database
            if job_id:
                try:
                    self.job_store.fail_job(
                        job_id, 
                        f"Worker callback error: {type(e).__name__}: {str(e)}"
                    )
                except Exception as db_error:
                    logger.error(f"Failed to update job status in DB: {db_error}")
    
    def process_job(self, job: Job):
        table_names = job.table_names
        is_multi_table = job.is_multi_table
        
        logger.info(
            f"Processing job {job.job_id} for {len(table_names)} table(s): {', '.join(table_names)}"
        )
        
        target_conn = None
        try:
            # Mark job as running with progress tracking
            self.job_store.update_job_status(job.job_id, JobStatus.RUNNING)
            logger.info(f"Job {job.job_id} marked as RUNNING")
            
            # Connect to target database
            target_conn = self._get_target_connection()
            
            # Profile table
            if is_multi_table:
                result = self._profile_multiple_tables(
                    target_conn, 
                    table_names, 
                    job.enable_ai_enrichment,
                    job.job_id
                )
            else:
                result = self._profile_single_table(
                    target_conn, 
                    table_names[0], 
                    job.enable_ai_enrichment
                )
            
            logger.info(f"Profiling completed for job {job.job_id}")
            
            # Save result
            self.job_store.complete_job(job.job_id, result)
            logger.info(f"Job {job.job_id} completed successfully")
            
        except Exception as e:
            # Catch all errors from profiling
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error(f"Job {job.job_id} failed: {error_msg}", exc_info=True)
            
            # Save error to database
            try:
                self.job_store.fail_job(job.job_id, error_msg)
                logger.info(f"Job {job.job_id} marked as FAILED")
            except Exception as db_error:
                logger.error(f"Failed to update job status: {db_error}")
            
        finally:
            # Close connection
            if target_conn:
                try:
                    target_conn.close()
                except Exception as e:
                    logger.error(f"Error closing target connection: {e}")
    
    def _profile_single_table(
        self, 
        conn, 
        table_name: str, 
        enable_ai: bool
    ) -> Dict[str, Any]:
        logger.info(f"Profiling single table: {table_name}")
        
        
        result = profile_table(conn, table_name)
        logger.info(f"Basic profiling completed for table {table_name}")
        
        result = self._transform_to_spec_format(result)
        
        if enable_ai:
            logger.info(f"AI enrichment enabled for table {table_name}")
            logger.info(f"ANTHROPIC_API_KEY present: {bool(os.getenv('ANTHROPIC_API_KEY'))}")
            try:
                result = enrich_profile_with_ai(result, fail_silently=False)
                logger.info(f"AI enrichment completed for table {table_name}")
            except Exception as ai_error:
                # AI enrichment failure should NOT fail the entire job
                logger.error(
                    f"AI enrichment failed for table {table_name}: {ai_error}",
                    exc_info=True
                )
                logger.info(f"Continuing without AI summary for {table_name}")
        
        return result
    
    def _transform_to_spec_format(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform profile to match spec field names.
        
        Transformations:
        - row_count -> approx_row_count (since we profile full table, this is exact)
        - Add sampled_rows field (equals approx_row_count for full profiling)
        """
        if 'row_count' in profile:
            profile['approx_row_count'] = profile['row_count']
            profile['sampled_rows'] = profile['row_count']  
        
        return profile
    
    def _profile_multiple_tables(
        self, 
        conn, 
        table_names: List[str], 
        enable_ai: bool,
        job_id: str
    ) -> Dict[str, Any]:
        logger.info(f"Profiling {len(table_names)} tables: {', '.join(table_names)}")
        
        profiles = []
        failed_tables = []
        tables_total = len(table_names)
        
        for idx, table_name in enumerate(table_names):
            try:
                logger.info(f"Profiling table {idx + 1}/{tables_total}: {table_name}...")
                
                # Update progress in database
                progress_info = {
                    "tables_total": tables_total,
                    "tables_completed": idx
                }
                self.job_store.update_job_progress(job_id, progress_info)
                logger.info(f"Progress: {idx}/{tables_total} tables completed")
                
                # Profile the table
                profile = self._profile_single_table(conn, table_name, enable_ai)
                profiles.append(profile)
                logger.info(f"Successfully profiled table {table_name}")
                
            except Exception as e:
                error_msg = f"Failed to profile table {table_name}: {type(e).__name__}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                failed_tables.append({
                    "table_name": table_name,
                    "error": str(e)
                })
        
        # If any tables failed raise exception 
        if failed_tables:
            failed_names = [t["table_name"] for t in failed_tables]
            raise Exception(
                f"Failed to profile {len(failed_tables)} table(s): {', '.join(failed_names)}. "
                f"Details: {json.dumps(failed_tables)}"
            )
        
        # Calculate summary statistics
        summary = {
            "total_tables": len(profiles),
            "total_rows": sum(p.get("approx_row_count", p.get("row_count", 0)) for p in profiles),
            "total_columns": sum(p.get("column_count", 0) for p in profiles)
        }
        
        logger.info(
            f"Multi-table profiling complete: {summary['total_tables']} tables, "
            f"{summary['total_rows']} total rows, {summary['total_columns']} total columns"
        )
        
        return {
            "tables": profiles,
            "summary": summary
        }
    
    def run_forever(self):
        self.running = True
        logger.info("Worker starting...")
        
        try:
            # Connect to RabbitMQ
            self.rabbitmq_conn.connect()
            
            self.rabbitmq_conn.setup_consumer(
                callback=self._message_callback,
                prefetch_count=1
            )
            
            logger.info("Worker ready, waiting for messages...")
            
            # Start consuming 
            self.rabbitmq_conn.start_consuming()
            
        except KeyboardInterrupt:
            logger.info("Worker interrupted by user (Ctrl+C)")
            self.stop()
            
        except Exception as e:
            logger.error(f"Fatal error in worker: {e}", exc_info=True)
            self.stop()
            raise
    
    def stop(self):
        logger.info("Stopping worker...")
        self.running = False
        
        try:
            self.rabbitmq_conn.stop_consuming()
            self.rabbitmq_conn.close()
            logger.info("Worker stopped successfully")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")


def main():

    load_dotenv()
    
    # Configuration from environment
    JOB_DB_PARAMS = {
        "host": os.getenv("JOB_DB_HOST", "localhost"),
        "database": os.getenv("JOB_DB_NAME", "profiling_jobs"),
        "user": os.getenv("JOB_DB_USER", "postgres"),
        "password": os.getenv("JOB_DB_PASSWORD"),
        "port": int(os.getenv("JOB_DB_PORT", "5432"))
    }
    
    TARGET_DB_PARAMS = {
        "host": os.getenv("TARGET_DB_HOST", "localhost"),
        "database": os.getenv("TARGET_DB_NAME", "your_data"),
        "user": os.getenv("TARGET_DB_USER", "postgres"),
        "password": os.getenv("TARGET_DB_PASSWORD"),
        "port": int(os.getenv("TARGET_DB_PORT", "5432"))
    }
    
    RABBITMQ_PARAMS = {
        "host": os.getenv("RABBITMQ_HOST", "localhost"),
        "port": int(os.getenv("RABBITMQ_PORT", "5672")),
        "username": os.getenv("RABBITMQ_USER", "guest"),
        "password": os.getenv("RABBITMQ_PASSWORD", "guest")
    }
    
    # Initialize job store
    job_store = JobStore(JOB_DB_PARAMS)
    job_store.initialize_schema()
    
    # Initialize RabbitMQ connection
    rabbitmq_conn = RabbitMQConnection(
        host=RABBITMQ_PARAMS['host'],
        port=RABBITMQ_PARAMS['port'],
        username=RABBITMQ_PARAMS['username'],
        password=RABBITMQ_PARAMS['password'],
        queue_name="profiling_jobs"
    )
    
    # Create and run worker
    worker = ProfileWorker(
        job_store=job_store,
        target_db_params=TARGET_DB_PARAMS,
        rabbitmq_conn=rabbitmq_conn
    )
    
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
    except Exception as e:
        logger.error(f"Worker stopped due to error: {e}")


if __name__ == "__main__":
    main()