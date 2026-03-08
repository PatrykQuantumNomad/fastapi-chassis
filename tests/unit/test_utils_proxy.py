"""Unit tests for proxy utility helpers."""

import pytest
from starlette.datastructures import Headers

from app.utils.proxy import (
    get_forwarded_client_ip,
    is_trusted_proxy,
    normalize_forwarded_proto,
    normalize_ip,
    parse_trusted_proxies,
)

pytestmark = pytest.mark.unit


class TestParseTrustedProxies:
    """Tests for parse_trusted_proxies."""

    def test_parses_single_ipv4(self) -> None:
        result = parse_trusted_proxies(["10.0.0.1/32"])
        assert len(result) == 1
        assert str(result[0]) == "10.0.0.1/32"

    def test_parses_multiple_cidrs(self) -> None:
        result = parse_trusted_proxies(["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"])
        assert len(result) == 3

    def test_empty_list_returns_empty_tuple(self) -> None:
        assert parse_trusted_proxies([]) == ()

    def test_parses_ipv6_cidr(self) -> None:
        result = parse_trusted_proxies(["::1/128", "fd00::/8"])
        assert len(result) == 2

    def test_non_strict_mode_normalizes_host_bits(self) -> None:
        result = parse_trusted_proxies(["10.0.0.5/8"])
        assert str(result[0]) == "10.0.0.0/8"

    def test_invalid_cidr_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            parse_trusted_proxies(["not-a-cidr"])


class TestIsTrustedProxy:
    """Tests for is_trusted_proxy."""

    def test_trusted_ipv4_in_network(self) -> None:
        proxies = parse_trusted_proxies(["10.0.0.0/8"])
        assert is_trusted_proxy("10.1.2.3", proxies) is True

    def test_untrusted_ipv4(self) -> None:
        proxies = parse_trusted_proxies(["10.0.0.0/8"])
        assert is_trusted_proxy("192.168.1.1", proxies) is False

    def test_invalid_ip_returns_false(self) -> None:
        proxies = parse_trusted_proxies(["10.0.0.0/8"])
        assert is_trusted_proxy("not-an-ip", proxies) is False

    def test_empty_string_returns_false(self) -> None:
        proxies = parse_trusted_proxies(["10.0.0.0/8"])
        assert is_trusted_proxy("", proxies) is False

    def test_empty_trusted_list_returns_false(self) -> None:
        assert is_trusted_proxy("10.0.0.1", ()) is False

    def test_ipv6_loopback(self) -> None:
        proxies = parse_trusted_proxies(["::1/128"])
        assert is_trusted_proxy("::1", proxies) is True

    def test_hostname_returns_false(self) -> None:
        proxies = parse_trusted_proxies(["10.0.0.0/8"])
        assert is_trusted_proxy("proxy.internal", proxies) is False


class TestNormalizeIp:
    """Tests for normalize_ip."""

    def test_valid_ipv4(self) -> None:
        assert normalize_ip("192.168.1.1") == "192.168.1.1"

    def test_valid_ipv6(self) -> None:
        assert normalize_ip("::1") == "::1"

    def test_strips_whitespace(self) -> None:
        assert normalize_ip("  10.0.0.1  ") == "10.0.0.1"

    def test_invalid_value_returns_none(self) -> None:
        assert normalize_ip("not-an-ip") is None

    def test_empty_string_returns_none(self) -> None:
        assert normalize_ip("") is None

    def test_cidr_notation_returns_none(self) -> None:
        assert normalize_ip("10.0.0.0/8") is None

    def test_normalizes_ipv6_representation(self) -> None:
        assert normalize_ip("0000:0000:0000:0000:0000:0000:0000:0001") == "::1"


class TestNormalizeForwardedProto:
    """Tests for normalize_forwarded_proto."""

    def test_none_returns_none(self) -> None:
        assert normalize_forwarded_proto(None) is None

    def test_http_returned(self) -> None:
        assert normalize_forwarded_proto("http") == "http"

    def test_https_returned(self) -> None:
        assert normalize_forwarded_proto("https") == "https"

    def test_case_insensitive(self) -> None:
        assert normalize_forwarded_proto("HTTPS") == "https"
        assert normalize_forwarded_proto("Http") == "http"

    def test_takes_first_value_from_comma_separated(self) -> None:
        assert normalize_forwarded_proto("https, http") == "https"

    def test_invalid_proto_returns_none(self) -> None:
        assert normalize_forwarded_proto("ftp") is None

    def test_empty_string_returns_none(self) -> None:
        assert normalize_forwarded_proto("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert normalize_forwarded_proto("   ") is None

    def test_garbage_value_returns_none(self) -> None:
        assert normalize_forwarded_proto("x-custom-proto") is None


class TestGetForwardedClientIp:
    """Tests for get_forwarded_client_ip."""

    def test_returns_none_when_no_headers_present(self) -> None:
        headers = Headers({})
        assert get_forwarded_client_ip(headers, ["x-forwarded-for"], ()) is None

    def test_returns_none_when_header_value_is_empty(self) -> None:
        headers = Headers({"x-forwarded-for": ""})
        assert get_forwarded_client_ip(headers, ["x-forwarded-for"], ()) is None

    def test_single_xff_ip(self) -> None:
        headers = Headers({"x-forwarded-for": "203.0.113.1"})
        assert get_forwarded_client_ip(headers, ["x-forwarded-for"], ()) == "203.0.113.1"

    def test_xff_all_trusted_returns_none(self) -> None:
        proxies = parse_trusted_proxies(["203.0.113.0/24", "10.0.0.0/8"])
        headers = Headers({"x-forwarded-for": "10.0.0.1, 203.0.113.1"})
        assert get_forwarded_client_ip(headers, ["x-forwarded-for"], proxies) is None

    def test_xff_all_invalid_returns_none(self) -> None:
        headers = Headers({"x-forwarded-for": "garbage, not-an-ip"})
        assert get_forwarded_client_ip(headers, ["x-forwarded-for"], ()) is None

    def test_non_xff_header_with_trusted_ip_skipped(self) -> None:
        proxies = parse_trusted_proxies(["10.0.0.0/8"])
        headers = Headers({"x-real-ip": "10.0.0.1"})
        assert get_forwarded_client_ip(headers, ["x-real-ip"], proxies) is None

    def test_non_xff_header_with_invalid_ip_skipped(self) -> None:
        headers = Headers({"x-real-ip": "not-valid"})
        assert get_forwarded_client_ip(headers, ["x-real-ip"], ()) is None

    def test_falls_through_to_second_header(self) -> None:
        proxies = parse_trusted_proxies(["10.0.0.0/8"])
        headers = Headers({"x-forwarded-for": "10.0.0.1", "x-real-ip": "203.0.113.5"})
        result = get_forwarded_client_ip(headers, ["x-forwarded-for", "x-real-ip"], proxies)
        assert result == "203.0.113.5"
