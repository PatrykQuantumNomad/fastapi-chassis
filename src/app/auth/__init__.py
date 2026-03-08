"""Authentication exports."""

from .dependencies import (
    get_current_principal,
    get_optional_principal,
    require_roles,
    require_scopes,
)
from .models import Principal
from .service import JWTAuthService

__all__ = [
    "JWTAuthService",
    "Principal",
    "get_current_principal",
    "get_optional_principal",
    "require_roles",
    "require_scopes",
]
