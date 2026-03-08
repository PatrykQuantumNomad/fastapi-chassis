"""
Unit tests for database ORM models.

Validates model constraints, defaults, and column behavior in isolation
using a temporary in-memory SQLite database.
"""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import ExampleWidget

pytestmark = pytest.mark.unit


@pytest.fixture
def engine() -> Engine:
    """In-memory SQLite engine with schema created from metadata."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """Transactional session rolled back after each test."""
    with Session(engine) as s:
        yield s


class TestExampleWidgetModel:
    """Tests for the ExampleWidget ORM model."""

    def test_table_name(self) -> None:
        assert ExampleWidget.__tablename__ == "example_widgets"

    def test_columns_exist(self, engine: Engine) -> None:
        columns = {c["name"] for c in inspect(engine).get_columns("example_widgets")}
        assert columns == {"id", "name", "created_at"}

    def test_primary_key_autoincrements(self, session: Session) -> None:
        w1 = ExampleWidget(name="widget-a")
        w2 = ExampleWidget(name="widget-b")
        session.add_all([w1, w2])
        session.flush()
        assert w1.id is not None
        assert w2.id is not None
        assert w2.id > w1.id

    def test_name_is_required(self, session: Session) -> None:
        widget = ExampleWidget()
        session.add(widget)
        with pytest.raises(IntegrityError):
            session.flush()

    def test_name_must_be_unique(self, session: Session) -> None:
        session.add(ExampleWidget(name="duplicate"))
        session.flush()
        session.add(ExampleWidget(name="duplicate"))
        with pytest.raises(IntegrityError):
            session.flush()

    def test_created_at_has_server_default(self, session: Session) -> None:
        widget = ExampleWidget(name="with-default-ts")
        session.add(widget)
        session.flush()
        session.refresh(widget)
        assert widget.created_at is not None
        assert isinstance(widget.created_at, datetime)

    def test_explicit_created_at_is_preserved(self, session: Session) -> None:
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        widget = ExampleWidget(name="explicit-ts", created_at=ts)
        session.add(widget)
        session.flush()
        session.refresh(widget)
        assert widget.created_at.year == 2025
        assert widget.created_at.month == 1

    def test_name_max_length_accepted(self, session: Session) -> None:
        widget = ExampleWidget(name="x" * 120)
        session.add(widget)
        session.flush()
        session.refresh(widget)
        assert len(widget.name) == 120

    def test_repr_contains_useful_info(self, session: Session) -> None:
        widget = ExampleWidget(name="repr-test")
        session.add(widget)
        session.flush()
        assert "ExampleWidget" in repr(widget)
