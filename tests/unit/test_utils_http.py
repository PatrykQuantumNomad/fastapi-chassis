"""Unit tests for HTTP utility helpers."""

from typing import TYPE_CHECKING

import pytest
from starlette.requests import Request

from app.utils.http import get_sanitized_request_path, get_sanitized_scope_path

if TYPE_CHECKING:
    from starlette.types import Scope

pytestmark = pytest.mark.unit


class TestGetSanitizedScopePath:
    """Tests for get_sanitized_scope_path."""

    def test_basic_path(self) -> None:
        scope: Scope = {"type": "http", "path": "/api/v1/items", "root_path": ""}
        assert get_sanitized_scope_path(scope) == "/api/v1/items"

    def test_with_root_path(self) -> None:
        scope: Scope = {"type": "http", "path": "/items", "root_path": "/api/v1"}
        assert get_sanitized_scope_path(scope) == "/api/v1/items"

    def test_strips_query_string_by_design(self) -> None:
        scope: Scope = {
            "type": "http",
            "path": "/search",
            "root_path": "",
            "query_string": b"token=secret&page=1",
        }
        result = get_sanitized_scope_path(scope)
        assert "token" not in result
        assert "secret" not in result
        assert result == "/search"

    def test_missing_path_defaults_to_slash(self) -> None:
        scope: Scope = {"type": "http", "root_path": ""}
        assert get_sanitized_scope_path(scope) == "/"

    def test_missing_root_path_treated_as_empty(self) -> None:
        scope: Scope = {"type": "http", "path": "/test"}
        assert get_sanitized_scope_path(scope) == "/test"

    def test_both_missing_defaults_to_slash(self) -> None:
        scope: Scope = {"type": "http"}
        assert get_sanitized_scope_path(scope) == "/"

    def test_empty_path_with_root_path(self) -> None:
        scope: Scope = {"type": "http", "path": "/", "root_path": "/prefix"}
        assert get_sanitized_scope_path(scope) == "/prefix/"

    def test_none_values_treated_as_empty(self) -> None:
        scope: Scope = {"type": "http", "path": None, "root_path": None}
        assert get_sanitized_scope_path(scope) == "/"


class TestGetSanitizedRequestPath:
    """Tests for get_sanitized_request_path."""

    def test_delegates_to_scope_function(self) -> None:
        scope: Scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/items",
            "root_path": "",
            "query_string": b"key=value",
            "headers": [],
        }
        request = Request(scope)
        assert get_sanitized_request_path(request) == "/api/items"
