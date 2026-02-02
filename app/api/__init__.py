"""
API package for table profiling service.

This package contains:
- FastAPI application (main.py)
- Request/response models (models.py)
- Dependency injection (dependencies.py)

To run the API:
    uvicorn app.api.main:app --reload
"""

from app.api.main import app

__all__ = ["app"]