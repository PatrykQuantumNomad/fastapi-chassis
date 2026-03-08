"""
Health check and utility routes.

Provides endpoints for infrastructure orchestration:
- / (root): API landing payload for local discovery
- configurable liveness path: "Is the process alive?"
- configurable readiness path: "Can the process accept traffic?"
- /info: Application metadata for debugging

In Kubernetes:
- A failing liveness check triggers a pod restart.
- A failing readiness check removes the pod from the service (no traffic).
These are fundamentally different failure modes requiring separate endpoints.

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response

from ..settings import Settings


def root(request: Request) -> dict[str, Any]:
    """
    API landing endpoint.

    Returns a lightweight payload for local browser checks so `/`
    does not emit a noisy 404 in access/error logs.
    """
    return {
        "status": "ok",
        "app": request.app.title,
        "version": request.app.version,
        "docs_url": request.app.docs_url,
        "redoc_url": request.app.redoc_url,
        "openapi_url": request.app.openapi_url,
    }


def health_check() -> dict[str, str]:
    """
    Liveness probe endpoint.

    Returns 200 if the process is alive and able to handle requests.
    This endpoint should be fast and have no external dependencies.
    """
    return {"status": "healthy"}


async def readiness_check(request: Request) -> JSONResponse:
    """
    Readiness probe endpoint.

    Returns 200 if the application is ready to accept traffic.
    Extend this with connectivity checks for databases, caches,
    and other critical dependencies.
    """
    registry = request.app.state.readiness_registry
    settings = request.app.state.settings
    results = await registry.run(request.app)
    checks = {
        result.name: result.as_payload(include_detail=settings.readiness_include_details)
        for result in results
    }
    all_healthy = all(result.is_healthy for result in results)
    status = "ready" if all_healthy else "not_ready"
    status_code = 200 if all_healthy else 503

    return JSONResponse(
        status_code=status_code,
        content={"status": status, "checks": checks},
    )


def favicon() -> Response:
    """
    Favicon placeholder endpoint for local browser visits.

    Browsers automatically request /favicon.ico when opening the API URL.
    Returning 204 avoids noisy 404 access logs in local development.
    """
    return Response(status_code=204)


def app_info(request: Request) -> dict[str, Any]:
    """
    Application metadata endpoint.

    Returns the application name and version. Useful for deployment
    verification and debugging.
    """
    settings = request.app.state.settings
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "debug": settings.debug,
    }


def list_endpoints(request: Request) -> JSONResponse:
    """
    List all registered routes in the application.

    Returns every route with its path, name, and allowed methods.
    Useful for API discovery and debugging.
    """
    endpoints: list[dict[str, str | list[str]]] = [
        {
            "path": route.path,
            "name": route.name,
            "methods": sorted(route.methods) if hasattr(route, "methods") else [],
        }
        for route in request.app.routes
        if hasattr(route, "path")
    ]

    return JSONResponse(content=jsonable_encoder({"endpoints": endpoints}))


def create_health_router(settings: Settings) -> APIRouter:
    """Create infrastructure routes using the configured health paths."""
    router = APIRouter()
    router.add_api_route("/", root, methods=["GET"], tags=["Utility"])
    router.add_api_route(
        settings.health_check_path,
        health_check,
        methods=["GET"],
        tags=["Health"],
    )
    router.add_api_route(
        settings.readiness_check_path,
        readiness_check,
        methods=["GET"],
        tags=["Health"],
    )
    router.add_api_route("/favicon.ico", favicon, methods=["GET"], include_in_schema=False)
    if settings.info_endpoint_enabled:
        router.add_api_route("/info", app_info, methods=["GET"], tags=["Utility"])
    if settings.endpoints_listing_enabled:
        router.add_api_route(
            "/endpoints",
            list_endpoints,
            methods=["GET"],
            response_class=JSONResponse,
            tags=["Utility"],
        )
    return router
