"""
FastAPI authentication and authorization dependencies.
"""

from collections.abc import Callable
from typing import cast

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .models import Principal
from .service import AuthenticationError, JWTAuthService

bearer_scheme = HTTPBearer(auto_error=False)


def get_auth_service(request: Request) -> JWTAuthService:
    """Return the configured auth service from application state."""
    return cast("JWTAuthService", request.app.state.auth_service)


async def get_optional_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),  # noqa: B008
) -> Principal | None:
    """Return the authenticated principal when a bearer token is provided."""
    if credentials is None:
        return None

    auth_service = get_auth_service(request)
    try:
        return await auth_service.authenticate_token(credentials.credentials)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_principal(
    principal: Principal | None = Depends(get_optional_principal),  # noqa: B008
) -> Principal:
    """Require and return an authenticated principal."""
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


def require_scopes(*required_scopes: str) -> Callable[..., Principal]:
    """Create a dependency enforcing OAuth-style scopes."""

    def dependency(principal: Principal = Depends(get_current_principal)) -> Principal:  # noqa: B008
        missing = [scope for scope in required_scopes if scope not in principal.scopes]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required scopes: {', '.join(missing)}",
            )
        return principal

    return dependency


def require_roles(*required_roles: str) -> Callable[..., Principal]:
    """Create a dependency enforcing application roles."""

    def dependency(principal: Principal = Depends(get_current_principal)) -> Principal:  # noqa: B008
        missing = [role for role in required_roles if role not in principal.roles]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required roles: {', '.join(missing)}",
            )
        return principal

    return dependency
