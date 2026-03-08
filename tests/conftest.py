"""
Root test configuration.

Registers custom pytest markers so they can be used without warnings and keeps
the test environment hermetic by ignoring local APP_* variables and `.env`
files from the repo root.

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

import os
from pathlib import Path

import pytest

__all__ = ["_isolate_app_settings"]


@pytest.fixture(autouse=True)
def _isolate_app_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Prevent local environment/config files from influencing test outcomes."""
    for key in tuple(os.environ):
        if key.startswith("APP_"):
            monkeypatch.delenv(key, raising=False)

    monkeypatch.chdir(tmp_path)
