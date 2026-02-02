from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import JSONResponse
import logging

from app.api.models import (
    CreateProfileRequest,
    CreateProfileResponse,
    ProfileResponse,
    ErrorResponse,
    HealthResponse,
    JobStatusEnum
)
from app.api.dependencies import (
    get_job_store,
    get_rabbitmq_publisher
)
from app.worker.job_store import JobStore
from app.worker.rabbitmq_connection import RabbitMQPublisher
from app.worker.models import Job, JobStatus


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Initialize FastAPI app
app = FastAPI(
    title="Data Profiling Microservice",
    description="API for asynchronous database table profiling with multi-table support",
    version="2.0.0"
)


@app.get("/")
def root():
    """
    Root endpoint - API information.
    """
    return {
        "service": "Data Profiling Microservice",
        "version": "2.0.0",
        "features": [
            "Single and multi-table profiling",
            "Top values for categorical columns",
            "Percentiles for numeric columns",
            "Optional AI-powered semantic enrichment"
        ],
        "endpoints": {
            "create_profile": "POST /profiles",
            "get_profile": "GET /profiles/{request_id}",
            "health": "GET /health"
        }
    }


@app.post(
    "/profiles",
    response_model=CreateProfileResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Profile request created and queued successfully"},
        400: {"model": ErrorResponse, "description": "Invalid request"},
        500: {"model": ErrorResponse, "description": "Internal server error"}
    }
)
def create_profile(
    request: CreateProfileRequest,
    job_store: JobStore = Depends(get_job_store),
    publisher: RabbitMQPublisher = Depends(get_rabbitmq_publisher)
):
    try:
        # Validate request
        table_list = request.get_table_list()
        
        if not table_list:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either 'table_name' or 'table_names' must be provided"
            )
        
        if len(table_list) > 50:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maximum 50 tables can be profiled in a single request"
            )
        
        table_name_str = ','.join(table_list)
        
        job = job_store.create_job(
            table_name=table_name_str,
            enable_ai_enrichment=request.enable_ai_enrichment
        )
        
        logger.info(
            f"Created profile request {job.job_id} for {len(table_list)} table(s): {table_name_str} "
            f"(AI enrichment: {request.enable_ai_enrichment})"
        )
        
        # Publish to RabbitMQ
        publisher.publish_job(job.job_id)
        logger.info(f"Published profile request {job.job_id} to queue")
        
        # Return response
        return CreateProfileResponse(
            request_id=job.job_id,
            status=JobStatusEnum.QUEUED,
            message=f"{'Multi-table' if len(table_list) > 1 else 'Single-table'} profile request queued successfully",
            table_count=len(table_list)
        )
        
    except HTTPException:
        # Re-raise validation errors
        raise
        
    except Exception as e:
        logger.error(f"Failed to create profile request: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create profile request: {str(e)}"
        )


@app.get(
    "/profiles/{request_id}",
    response_model=ProfileResponse,
    responses={
        200: {"description": "Profile request found"},
        404: {"model": ErrorResponse, "description": "Profile request not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"}
    }
)
def get_profile(
    request_id: str,
    job_store: JobStore = Depends(get_job_store)
):
    try:
        # Fetch job from database
        job = job_store.get_job(request_id)
        
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile request with id '{request_id}' not found"
            )
        
        # Convert JobStatus enum to JobStatusEnum string
        status_map = {
            JobStatus.QUEUED: JobStatusEnum.QUEUED,
            JobStatus.RUNNING: JobStatusEnum.RUNNING,
            JobStatus.COMPLETED: JobStatusEnum.COMPLETED,
            JobStatus.FAILED: JobStatusEnum.FAILED,
            "QUEUED": JobStatusEnum.QUEUED,
            "RUNNING": JobStatusEnum.RUNNING,
            "COMPLETED": JobStatusEnum.COMPLETED,
            "FAILED": JobStatusEnum.FAILED
        }
        
        # Use completed_at as updated_at, or started_at, or created_at as fallback
        updated_at = job.completed_at or job.started_at or job.created_at
        
        # Wrap result in {"profile": ...}
        wrapped_profile = None
        if job.result is not None:
            wrapped_profile = {"profile": job.result}
        
        # Return profile response
        return ProfileResponse(
            request_id=job.job_id,
            table_name=job.table_name,
            status=status_map[job.status],
            created_at=job.created_at,
            updated_at=updated_at,
            profile=wrapped_profile, 
            error_message=job.error
        )
        
    except HTTPException:
        raise
        
    except Exception as e:
        logger.error(f"Failed to fetch profile request {request_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch profile request: {str(e)}"
        )


@app.get(
    "/health",
    response_model=HealthResponse,
    responses={
        200: {"description": "Service healthy"},
        503: {"model": ErrorResponse, "description": "Service unhealthy"}
    }
)
def health_check(
    job_store: JobStore = Depends(get_job_store),
    publisher: RabbitMQPublisher = Depends(get_rabbitmq_publisher)
):
    db_status = "unknown"
    rabbitmq_status = "unknown"
    overall_status = "unhealthy"
    
    try:
        job_store.initialize_schema()  
        db_status = "connected"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = "error"
    
    try:
        rabbitmq_status = "connected"
    except Exception as e:
        logger.error(f"RabbitMQ health check failed: {e}")
        rabbitmq_status = "error"
    
    # Overall status
    if db_status == "connected" and rabbitmq_status == "connected":
        overall_status = "healthy"
    
    response = HealthResponse(
        status=overall_status,
        database=db_status,
        rabbitmq=rabbitmq_status
    )
    
    # Return 503 if unhealthy
    if overall_status != "healthy":
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=response.model_dump()
        )
    
    return response


# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal server error",
            "detail": "An unexpected error occurred"
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)