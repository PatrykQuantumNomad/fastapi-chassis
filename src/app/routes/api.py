"""
Example API routes using stateless JWT authentication and authorization.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request

from ..auth import Principal, get_current_principal, require_roles, require_scopes
from ..cache import CacheStore, get_cache

router = APIRouter(prefix="/api/v1", tags=["API"])
reports_reader = require_scopes("reports:read")
admin_role = require_roles("admin")


@router.get("/me")
async def get_me(principal: Principal = Depends(get_current_principal)) -> dict[str, object]:  # noqa: B008
    """Return the authenticated principal payload."""
    return {
        "subject": principal.subject,
        "issuer": principal.issuer,
        "audience": principal.audience,
        "scopes": principal.scopes,
        "roles": principal.roles,
    }


@router.get("/reports")
async def get_reports(
    principal: Principal = Depends(reports_reader),  # noqa: B008
) -> dict[str, object]:
    """Example scope-protected route."""
    return {"status": "ok", "subject": principal.subject, "report_access": True}


@router.get("/admin")
async def get_admin_dashboard(
    principal: Principal = Depends(admin_role),  # noqa: B008
) -> dict[str, object]:
    """Example role-protected route."""
    return {"status": "ok", "subject": principal.subject, "admin": True}


@router.get("/cached-time")
async def get_cached_time(request: Request) -> dict[str, object]:
    """Example endpoint demonstrating the optional cache layer."""
    settings = request.app.state.settings
    if not settings.cache_enabled:
        return {"time": datetime.now(UTC).isoformat(), "source": "live", "cache": "disabled"}

    cache: CacheStore = get_cache(request)
    key = "example:current_time"
    cached = await cache.get(key)
    if cached is not None:
        return {"time": cached.decode(), "source": "cache"}

    now = datetime.now(UTC).isoformat()
    await cache.set(key, now.encode(), ttl_seconds=settings.cache_default_ttl_seconds)
    return {"time": now, "source": "live"}
