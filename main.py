"""
Application entry point.

Creates the FastAPI application using the factory method and provides
a Uvicorn runner for local development.

Production deployments should use:
    uvicorn main:app --host 127.0.0.1 --port 8000 --workers 4 --no-access-log

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

import uvicorn

from app import create_app
from app.settings import Settings

settings = Settings()

# Create the importable ASGI application instance referenced by `main:app`.
app = create_app(settings=settings)

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
        log_config=settings.logging_config_path,
        access_log=False,
    )
