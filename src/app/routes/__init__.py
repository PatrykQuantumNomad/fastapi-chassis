"""Application route modules."""

from .api import router as api_router
from .health import create_health_router

__all__ = ["api_router", "create_health_router"]
