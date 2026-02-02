from enum import Enum
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class Job:
    job_id: str
    status: str
    table_name: str  
    enable_ai_enrichment: bool = False
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    @property
    def table_names(self) -> List[str]:
        if not self.table_name:
            return []
        return [t.strip() for t in self.table_name.split(',')]
    
    @property
    def is_multi_table(self) -> bool:
        # Check if this is a multi-table job
        return len(self.table_names) > 1