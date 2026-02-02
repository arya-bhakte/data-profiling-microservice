import uuid
from datetime import datetime
from typing import Optional, Dict, Any
import psycopg2
from psycopg2.extras import RealDictCursor
import json
from decimal import Decimal
from app.worker.models import Job

class DecimalEncoder(json.JSONEncoder):
    # Custom JSON encoder to handle Decimal types from database queries
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


class JobStore:
    def __init__(self, conn_params: Dict[str, str]):
        # conn_params: dict with keys: host, database, user, password, port
        self.conn_params = conn_params
    
    def _get_connection(self):
        # Get a new database connection
        return psycopg2.connect(**self.conn_params)
    
    def initialize_schema(self):
        schema_sql = """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id VARCHAR(36) PRIMARY KEY,
            status VARCHAR(20) NOT NULL,
            table_name VARCHAR(255) NOT NULL,
            enable_ai_enrichment BOOLEAN DEFAULT FALSE,
            result JSONB,
            error TEXT,
            created_at TIMESTAMP NOT NULL,
            started_at TIMESTAMP,
            completed_at TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_jobs_status 
        ON jobs(status) 
        WHERE status IN ('QUEUED', 'RUNNING');
        """
        
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(schema_sql)
                conn.commit()
        finally:
            conn.close()
    
    def create_job(self, table_name: str, enable_ai_enrichment: bool = False) -> Job:
        job = Job(
            job_id=str(uuid.uuid4()),
            status="QUEUED",
            table_name=table_name,
            enable_ai_enrichment=enable_ai_enrichment,
            created_at=datetime.utcnow()
        )
        
        insert_sql = """
        INSERT INTO jobs (job_id, status, table_name, enable_ai_enrichment, created_at)
        VALUES (%s, %s, %s, %s, %s)
        """
        
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(insert_sql, (
                    job.job_id,
                    job.status,
                    job.table_name,
                    job.enable_ai_enrichment,
                    job.created_at
                ))
                conn.commit()
        finally:
            conn.close()
        
        return job
    
    def get_job(self, job_id: str) -> Optional[Job]:
        query_sql = """
        SELECT job_id, status, table_name, enable_ai_enrichment, result, error,
               created_at, started_at, completed_at
        FROM jobs
        WHERE job_id = %s
        """
        
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query_sql, (job_id,))
                row = cursor.fetchone()
                
                if not row:
                    return None
                
                return Job(
                    job_id=row['job_id'],
                    status=row['status'],
                    table_name=row['table_name'],
                    enable_ai_enrichment=row.get('enable_ai_enrichment', False),
                    result=row['result'],
                    error=row['error'],
                    created_at=row['created_at'],
                    started_at=row['started_at'],
                    completed_at=row['completed_at']
                )
        finally:
            conn.close()
    
    
    def update_job_status(self, job_id: str, status: str):
        update_sql = """
        UPDATE jobs
        SET status = %s,
            started_at = CASE 
                WHEN %s = 'RUNNING' AND started_at IS NULL 
                THEN %s 
                ELSE started_at 
            END
        WHERE job_id = %s
        """
        
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(update_sql, (
                    status,
                    status,
                    datetime.utcnow(),
                    job_id
                ))
                conn.commit()
        finally:
            conn.close()
    
    def update_job_progress(self, job_id: str, progress_info: Dict[str, Any]):
        update_sql = """
        UPDATE jobs
        SET result = %s
        WHERE job_id = %s AND status = 'RUNNING'
        """
        
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(update_sql, (
                    json.dumps(progress_info, cls=DecimalEncoder),
                    job_id
                ))
                conn.commit()
        finally:
            conn.close()
            
    def complete_job(self, job_id: str, result: Dict[str, Any]):
        update_sql = """
        UPDATE jobs
        SET status = 'COMPLETED',
            result = %s,
            completed_at = %s
        WHERE job_id = %s
        """
        
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(update_sql, (
                    json.dumps(result, cls=DecimalEncoder),
                    datetime.utcnow(),
                    job_id
                ))
                conn.commit()
        finally:
            conn.close()
    
    def fail_job(self, job_id: str, error: str):
        update_sql = """
        UPDATE jobs
        SET status = 'FAILED',
            error = %s,
            completed_at = %s
        WHERE job_id = %s
        """
        
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(update_sql, (
                    error,
                    datetime.utcnow(),
                    job_id
                ))
                conn.commit()
        finally:
            conn.close()