"""
Example ORM models for the template.

The template ships with one minimal model so migrations and metadata
discovery work out of the box.
"""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ExampleWidget(Base):
    """Small example model proving the SQLite ORM and migrations are wired."""

    __tablename__ = "example_widgets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
