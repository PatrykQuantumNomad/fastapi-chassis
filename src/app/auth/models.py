"""
Authentication domain models.
"""

from typing import Any

from pydantic import BaseModel, Field


class Principal(BaseModel):
    """Authenticated principal extracted from a validated JWT."""

    subject: str = Field(description="JWT subject claim")
    issuer: str | None = Field(default=None, description="Token issuer")
    audience: list[str] = Field(default_factory=list, description="Normalized audience values")
    scopes: list[str] = Field(default_factory=list, description="Granted OAuth scopes")
    roles: list[str] = Field(default_factory=list, description="Application roles")
    claims: dict[str, Any] = Field(default_factory=dict, description="Full validated claim set")
