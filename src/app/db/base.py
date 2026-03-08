"""
SQLAlchemy metadata base.

Centralizes ORM metadata for both runtime model imports and Alembic
autogeneration.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all ORM models in the application."""
