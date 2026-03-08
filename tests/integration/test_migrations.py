"""
Integration tests for Alembic migrations.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

pytestmark = pytest.mark.integration


def test_alembic_upgrade_creates_example_widget_table(tmp_path: Path) -> None:
    """Running Alembic upgrades creates the shipped example table."""
    repo_root = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "migration.db"

    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

    command.upgrade(config, "head")

    with closing(sqlite3.connect(database_path)) as connection:
        result = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='example_widgets'"
        ).fetchone()

    assert result is not None


def test_alembic_uses_env_configured_database_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """APP_ALEMBIC_DATABASE_URL drives migrations when alembic.ini leaves the URL unset."""
    repo_root = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "env-migration.db"
    monkeypatch.setenv("APP_ALEMBIC_DATABASE_URL", f"sqlite:///{database_path}")

    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))

    command.upgrade(config, "head")

    with closing(sqlite3.connect(database_path)) as connection:
        result = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='example_widgets'"
        ).fetchone()

    assert result is not None


def test_alembic_downgrade_removes_example_widget_table(tmp_path: Path) -> None:
    """Rolling back the initial migration removes the example_widgets table."""
    repo_root = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "rollback.db"

    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

    command.upgrade(config, "head")

    with closing(sqlite3.connect(database_path)) as connection:
        result = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='example_widgets'"
        ).fetchone()
    assert result is not None

    command.downgrade(config, "-1")

    with closing(sqlite3.connect(database_path)) as connection:
        result = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='example_widgets'"
        ).fetchone()
    assert result is None
