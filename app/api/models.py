from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum


class JobStatusEnum(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CreateProfileRequest(BaseModel):
    table_name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=255,
        description="Name of a single table to profile (deprecated, use table_names instead)",
        examples=["users", "orders", "public.customers"]
    )
    table_names: Optional[List[str]] = Field(
        None,
        min_items=1,
        max_items=50,
        description="List of table names to profile (supports multi-table profiling)",
        examples=[["users", "orders"], ["public.customers", "public.products"]]
    )
    enable_ai_enrichment: bool = Field(
        default=False,
        description="Enable AI-generated semantic summary of profiling results"
    )
    
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "table_name": "users",
                    "enable_ai_enrichment": True
                },
                {
                    "table_names": ["users", "orders", "products"],
                    "enable_ai_enrichment": False
                }
            ]
        }
    
    def get_table_list(self) -> List[str]:
        if self.table_names:
            return self.table_names
        elif self.table_name:
            return [self.table_name]
        else:
            return []


class ProfileResponse(BaseModel):
    request_id: str
    table_name: str  # Single table or comma-separated list
    status: JobStatusEnum
    created_at: datetime
    updated_at: datetime
    profile: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "request_id": "abc-123",
                    "table_name": "users",
                    "status": "COMPLETED",
                    "created_at": "2024-01-15T10:30:00",
                    "updated_at": "2024-01-15T10:35:00",
                    "profile": {
                        "profile": {
                            "table_name": "users",
                            "approx_row_count": 1000,
                            "sampled_rows": 1000,
                            "column_count": 5,
                            "columns": [],
                            "statistics": {}
                        }
                    },
                    "error_message": None
                },
                {
                    "request_id": "def-456",
                    "table_name": "users,orders",
                    "status": "RUNNING",
                    "created_at": "2024-01-15T10:30:00",
                    "updated_at": "2024-01-15T10:32:00",
                    "profile": {
                        "profile": {
                            "tables_total": 2,
                            "tables_completed": 1
                        }
                    },
                    "error_message": None
                }
            ]
        }


class CreateProfileResponse(BaseModel):
    request_id: str
    status: JobStatusEnum
    message: str = "Profile request queued successfully"
    table_count: int = Field(
        default=1,
        description="Number of tables being profiled"
    )
    
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "request_id": "abc-123",
                    "status": "QUEUED",
                    "message": "Profile request queued successfully",
                    "table_count": 1
                },
                {
                    "request_id": "def-456",
                    "status": "QUEUED",
                    "message": "Multi-table profile request queued successfully",
                    "table_count": 3
                }
            ]
        }


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "error": "Profile request not found",
                "detail": "Profile request with id 'abc-123' does not exist"
            }
        }


class HealthResponse(BaseModel):
    status: str
    database: str
    rabbitmq: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "healthy",
                "database": "connected",
                "rabbitmq": "connected"
            }
        }